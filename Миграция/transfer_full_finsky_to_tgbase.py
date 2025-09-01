#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полный перенос из finsky.sqlite (источник) в tg_base.sqlite (приёмник) «всё, что можно физически положить»,
без изменения структуры приёмника. Скрипт сам анализирует схемы и переносит данные для следующих сущностей:

- users                (из clients)
- participant_settings (из clients.is_tester)
- participant_messages (из chat_messages + chats + clients)
- questions            (из support_requests + clients)
- question_messages    (из answers, биндится к questions по user_tg_id/text/create_dt)
- images               (из chat_messages.files)
- last_image           (по последней картинке пользователя)
- user_params          (last_message_id из chat_messages.telegram_data.message_id, last_image_message_list — список message_id с файлами)
- user_extended        (username + последний telegram_data как all_data)
- visite_log           (приближённо по updated_at|created_at клиентов, одно посещение на дату)

Если каких-то таблиц-источников нет — соответствующие разделы пропускаются.
Все вставки идемпотентны (повторный запуск не размножает данные).

Запуск:
    python transfer_full_finsky_to_tgbase.py /path/to/finsky.sqlite /path/to/tg_base.sqlite
"""

import sqlite3, sys, json
from collections import defaultdict

def table_exists(cur, name):
    row = cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone()
    return row is not None

def colnames(cur, table):
    return [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]

def boolify(v):
    if v is None: return None
    if isinstance(v, (int, float)): return 1 if v else 0
    s = str(v).strip().lower()
    if s in ('t','true','1','yes','y','on'): return 1
    if s in ('f','false','0','no','n','off',''): return 0
    return None

def main(src_path, dst_path):
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    src.row_factory = sqlite3.Row
    dst.row_factory = sqlite3.Row
    s = src.cursor(); d = dst.cursor()

    # --- наличие таблиц в источнике ---
    has_clients = table_exists(s, "clients")
    has_chats   = table_exists(s, "chats")
    has_msgs    = table_exists(s, "chat_messages")
    has_support = table_exists(s, "support_requests")
    has_answers = table_exists(s, "answers")
    has_settings= table_exists(s, "settings")

    # --- проверка приёмника ---
    must_have = ["users"]
    for t in must_have:
        assert table_exists(d, t), f"В приёмнике нет требуемой таблицы: {t}"

    # ускоряем вставки
    for pragma in ["PRAGMA synchronous=OFF;", "PRAGMA journal_mode=OFF;", "PRAGMA temp_store=MEMORY;", "PRAGMA cache_size=-50000;"]:
        d.execute(pragma)

    # ---------------- users ----------------
    if has_clients and table_exists(d, "users"):
        print("Перенос users ...")
        d.execute("BEGIN;")
        try:
            cols_dst = colnames(d, "users")
            want = ["tg_id","name","age_18","phone","create_dt"]
            ins_cols = [c for c in want if c in cols_dst]
            placeholders = ",".join(["?"]*len(ins_cols))
            insert_sql = f'INSERT OR IGNORE INTO users ({",".join(ins_cols)}) VALUES ({placeholders})'
            update_sql = 'UPDATE users SET name=COALESCE(?, name) WHERE tg_id=?'

            for row in s.execute("""
                SELECT telegram_id, created_at, updated_at
                FROM clients
                WHERE telegram_id IS NOT NULL
            """):
                tg_id = row["telegram_id"]
                name = None
                phone = None
                age_18 = None
                create_dt = row["created_at"]
                # insert
                vals = []
                for c in ins_cols:
                    if c == "tg_id": vals.append(tg_id)
                    elif c == "name": vals.append(name)
                    elif c == "age_18": vals.append(age_18)
                    elif c == "phone": vals.append(phone)
                    elif c == "create_dt": vals.append(create_dt)
                d.execute(insert_sql, vals)
                d.execute(update_sql, (name, tg_id))
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- participant_settings (tester/blocked) --------
    if has_clients and table_exists(d, "participant_settings"):
        print("Перенос participant_settings ...")
        d.execute("BEGIN;")
        try:
            cols_dst = colnames(d, "participant_settings")
            want = ["user_tg_id","blocked","tester","create_dt"]
            ins_cols = [c for c in want if c in cols_dst]
            placeholders = ",".join(["?"]*len(ins_cols))
            insert_sql = f'INSERT OR IGNORE INTO participant_settings ({",".join(ins_cols)}) VALUES ({placeholders})'
            update_sql = 'UPDATE participant_settings SET tester=COALESCE(?, tester) WHERE user_tg_id=?'

            for row in s.execute("""
                SELECT telegram_id, is_tester, created_at
                FROM clients
                WHERE telegram_id IS NOT NULL
            """):
                tg_id = row["telegram_id"]
                tester = boolify(row["is_tester"])
                blocked = 0
                create_dt = row["created_at"]
                vals = []
                for c in ins_cols:
                    if c == "user_tg_id": vals.append(tg_id)
                    elif c == "blocked": vals.append(blocked)
                    elif c == "tester": vals.append(tester)
                    elif c == "create_dt": vals.append(create_dt)
                d.execute(insert_sql, vals)
                d.execute(update_sql, (tester, tg_id))
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- participant_messages --------
    if has_msgs and has_chats and has_clients and table_exists(d, "participant_messages"):
        print("Перенос participant_messages ...")
        d.execute("BEGIN;")
        try:
            cols_dst = colnames(d, "participant_messages")
            want = ["user_tg_id","sender","text","is_answer","is_deleted","buttons","media","timestamp"]
            ins_cols = [c for c in want if c in cols_dst]
            placeholders = ",".join(["?"]*len(ins_cols))
            insert_sql = f'INSERT INTO participant_messages ({",".join(ins_cols)}) VALUES ({placeholders})'

            for row in s.execute("""
                SELECT cm.id, cm.chat_id, cm.from_client, cm.text, cm.files, cm.created_at,
                       cl.telegram_id, cm.telegram_data
                FROM chat_messages cm
                JOIN chats c    ON c.id = cm.chat_id
                JOIN clients cl ON cl.id = c.client_id
                WHERE cl.telegram_id IS NOT NULL
                ORDER BY cm.id
            """):
                tg_id = row["telegram_id"]
                sender = "client" if boolify(row["from_client"]) == 1 else "bot"
                text   = row["text"]
                media  = row["files"]
                is_answer = 0
                is_deleted = 0
                buttons = None
                ts     = row["created_at"]

                # idempotent: skip if same user/text/timestamp exists
                exists = d.execute(
                    'SELECT 1 FROM participant_messages WHERE user_tg_id=? AND IFNULL(text,"")=IFNULL(?, "") AND IFNULL(timestamp,"")=IFNULL(?, "") LIMIT 1',
                    (tg_id, text, ts)
                ).fetchone()
                if exists: continue

                vals = []
                for c in ins_cols:
                    if c == "user_tg_id": vals.append(tg_id)
                    elif c == "sender": vals.append(sender)
                    elif c == "text": vals.append(text)
                    elif c == "is_answer": vals.append(is_answer)
                    elif c == "is_deleted": vals.append(is_deleted)
                    elif c == "buttons": vals.append(buttons)
                    elif c == "media": vals.append(media)
                    elif c == "timestamp": vals.append(ts)
                d.execute(insert_sql, vals)
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- questions --------
    if has_support and has_clients and table_exists(d, "questions"):
        print("Перенос questions ...")
        d.execute("BEGIN;")
        try:
            cols_dst = colnames(d, "questions")
            want = ["user_tg_id","text","type","status","create_dt"]
            ins_cols = [c for c in want if c in cols_dst]
            placeholders = ",".join(["?"]*len(ins_cols))
            insert_sql = f'INSERT INTO questions ({",".join(ins_cols)}) VALUES ({placeholders})'

            for row in s.execute("""
                SELECT r.id as req_id, r.client_id, r.message, r.created_at, r.deleted_at, cl.telegram_id
                FROM support_requests r
                JOIN clients cl ON cl.id = r.client_id
                WHERE cl.telegram_id IS NOT NULL
                ORDER BY r.id
            """):
                tg_id = row["telegram_id"]
                text = row["message"]
                type_ = "support"
                status = "deleted" if row["deleted_at"] else "new"
                create_dt = row["created_at"]

                exists = d.execute(
                    'SELECT id FROM questions WHERE user_tg_id=? AND IFNULL(text,"")=IFNULL(?, "") AND IFNULL(create_dt,"")=IFNULL(?, "") LIMIT 1',
                    (tg_id, text, create_dt)
                ).fetchone()
                if exists: 
                    # optionally update status if newer info says deleted
                    if status == "deleted":
                        d.execute("UPDATE questions SET status=? WHERE id=?", (status, exists[0]))
                    continue

                vals = []
                for c in ins_cols:
                    if c == "user_tg_id": vals.append(tg_id)
                    elif c == "text": vals.append(text)
                    elif c == "type": vals.append(type_)
                    elif c == "status": vals.append(status)
                    elif c == "create_dt": vals.append(create_dt)
                d.execute(insert_sql, vals)
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- question_messages (из answers) --------
    if has_answers and has_support and table_exists(d, "question_messages") and table_exists(d, "questions"):
        print("Перенос question_messages ...")
        d.execute("BEGIN;")
        try:
            cols_dst = colnames(d, "question_messages")
            want = ["question_id","sender","text","is_answer","timestamp"]
            ins_cols = [c for c in want if c in cols_dst]
            placeholders = ",".join(["?"]*len(ins_cols))
            insert_sql = f'INSERT INTO question_messages ({",".join(ins_cols)}) VALUES ({placeholders})'

            # для каждого ответа найдём соответствующий question_id в приёмнике через уникальную связку
            for row in s.execute("""
                SELECT a.id, a.client_id, a.question_id, a.answer, a.created_at,
                       r.message AS req_message, r.created_at AS req_created_at,
                       cl.telegram_id
                FROM answers a
                JOIN support_requests r ON r.id = a.question_id
                JOIN clients cl ON cl.id = a.client_id
                WHERE cl.telegram_id IS NOT NULL
                ORDER BY a.id
            """):
                tg_id = row["telegram_id"]
                q_text = row["req_message"]
                q_create = row["req_created_at"]
                # найти целевой question.id
                qrow = d.execute(
                    'SELECT id FROM questions WHERE user_tg_id=? AND IFNULL(text,"")=IFNULL(?, "") AND IFNULL(create_dt,"")=IFNULL(?, "") LIMIT 1',
                    (tg_id, q_text, q_create)
                ).fetchone()
                if not qrow:
                    # если вопрос не перенесён (не должен), пропускаем
                    continue
                qid = qrow[0]

                sender = "client"
                text = row["answer"]
                is_answer = 1
                ts = row["created_at"]

                # идемпотентность: не дублировать одинаковые сообщения для вопроса
                exists = d.execute(
                    'SELECT 1 FROM question_messages WHERE question_id=? AND IFNULL(text,"")=IFNULL(?, "") AND IFNULL(timestamp,"")=IFNULL(?, "") LIMIT 1',
                    (qid, text, ts)
                ).fetchone()
                if exists: 
                    continue

                vals = []
                for c in ins_cols:
                    if c == "question_id": vals.append(qid)
                    elif c == "sender": vals.append(sender)
                    elif c == "text": vals.append(text)
                    elif c == "is_answer": vals.append(is_answer)
                    elif c == "timestamp": vals.append(ts)
                d.execute(insert_sql, vals)
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- images + last_image --------
    if has_msgs and has_chats and has_clients and table_exists(d, "images"):
        print("Перенос images / last_image ...")
        d.execute("BEGIN;")
        try:
            # соберём все картинки по пользователям
            img_rows = s.execute("""
                SELECT cm.id AS msg_id, cl.telegram_id AS tg_id, cm.created_at, cm.files
                FROM chat_messages cm
                JOIN chats c    ON c.id = cm.chat_id
                JOIN clients cl ON cl.id = c.client_id
                WHERE cm.files IS NOT NULL AND TRIM(cm.files) <> '' AND cl.telegram_id IS NOT NULL
                ORDER BY cm.id
            """).fetchall()

            # вставим файлы
            for r in img_rows:
                tg_id = r["tg_id"]
                ts = r["created_at"]
                files_json = r["files"]
                try:
                    files = json.loads(files_json)
                    if not isinstance(files, list):
                        files = [str(files)]
                except Exception:
                    files = [files_json] if files_json else []
                for fname in files:
                    # идемпотентность: не вставлять дубликат того же файла в то же время
                    ex = d.execute('SELECT id FROM images WHERE user_tg_id=? AND filename=? AND IFNULL(upload_dt,"")=IFNULL(?, "") LIMIT 1', (tg_id, fname, ts)).fetchone()
                    if ex: continue
                    d.execute('INSERT INTO images (filename, filepath, user_tg_id, upload_dt) VALUES (?,?,?,?)',
                              (fname, 'uploads', tg_id, ts))

            # last_image: выбрать последнюю по upload_dt для каждого user
            if table_exists(d, "last_image"):
                # очистка и восстановление последнего изображения для пользователей из источника
                # (не трогаем тех, у кого ничего не добавляли)
                user_ids = set([r["tg_id"] for r in img_rows])
                for uid in user_ids:
                    last = d.execute('SELECT id, upload_dt FROM images WHERE user_tg_id=? ORDER BY upload_dt DESC, id DESC LIMIT 1', (uid,)).fetchone()
                    if not last: continue
                    image_id, dt = last
                    ex = d.execute('SELECT 1 FROM last_image WHERE user_tg_id=?', (uid,)).fetchone()
                    if ex:
                        d.execute('UPDATE last_image SET image_id=?, create_dt=? WHERE user_tg_id=?', (image_id, dt, uid))
                    else:
                        d.execute('INSERT INTO last_image (image_id, user_tg_id, create_dt) VALUES (?,?,?)', (image_id, uid, dt))
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- user_params (last_message_id, last_image_message_list) --------
    if has_msgs and has_chats and has_clients and table_exists(d, "user_params"):
        print("Перенос user_params ...")
        d.execute("BEGIN;")
        try:
            # последние message_id по пользователю
            # берём последнюю запись по created_at и парсим telegram_data.message_id
            for row in s.execute("""
                SELECT cl.telegram_id AS tg_id, cm.telegram_data, cm.created_at
                FROM chat_messages cm
                JOIN chats c    ON c.id = cm.chat_id
                JOIN clients cl ON cl.id = c.client_id
                WHERE cl.telegram_id IS NOT NULL
                ORDER BY cm.created_at DESC
            """):
                tg_id = row["tg_id"]
                last_msg_id = None
                if row["telegram_data"]:
                    try:
                        obj = json.loads(row["telegram_data"])
                        last_msg_id = obj.get("message_id")
                    except Exception:
                        pass
                # собираем список message_id, где есть files
                # (можно сделать позже единоразово, чтобы не тратить много запросов)
                ex = d.execute('SELECT 1 FROM user_params WHERE user_tg_id=?', (tg_id,)).fetchone()
                if ex:
                    d.execute('UPDATE user_params SET last_message_id=COALESCE(?, last_message_id) WHERE user_tg_id=?', (last_msg_id, tg_id))
                else:
                    d.execute('INSERT INTO user_params (user_tg_id, last_message_id, last_image_message_list, create_dt) VALUES (?,?,?,CURRENT_TIMESTAMP)',
                              (tg_id, last_msg_id, None))
            # список message_id с files
            file_msgs = s.execute("""
                SELECT cl.telegram_id AS tg_id, cm.telegram_data
                FROM chat_messages cm
                JOIN chats c    ON c.id = cm.chat_id
                JOIN clients cl ON cl.id = c.client_id
                WHERE cm.files IS NOT NULL AND TRIM(cm.files) <> '' AND cl.telegram_id IS NOT NULL
            """).fetchall()
            per_user = defaultdict(list)
            for r in file_msgs:
                tg_id = r["tg_id"]
                if not r["telegram_data"]: continue
                try:
                    obj = json.loads(r["telegram_data"])
                    mid = obj.get("message_id")
                    if mid is not None:
                        per_user[tg_id].append(mid)
                except Exception:
                    pass
            for uid, mids in per_user.items():
                mids_json = json.dumps(mids, ensure_ascii=False)
                ex = d.execute('SELECT 1 FROM user_params WHERE user_tg_id=?', (uid,)).fetchone()
                if ex:
                    d.execute('UPDATE user_params SET last_image_message_list=? WHERE user_tg_id=?', (mids_json, uid))
                else:
                    d.execute('INSERT INTO user_params (user_tg_id, last_message_id, last_image_message_list, create_dt) VALUES (?,?,?,CURRENT_TIMESTAMP)',
                              (uid, None, mids_json))
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- user_extended (username + last telegram_data) --------
    if has_msgs and has_chats and has_clients and table_exists(d, "user_extended"):
        print("Перенос user_extended ...")
        d.execute("BEGIN;")
        try:
            # возьмём последнюю telegram_data по пользователю
            rows = s.execute("""
                SELECT cl.telegram_id AS tg_id, cm.telegram_data, cm.created_at
                FROM chat_messages cm
                JOIN chats c    ON c.id = cm.chat_id
                JOIN clients cl ON cl.id = c.client_id
                WHERE cm.telegram_data IS NOT NULL AND cl.telegram_id IS NOT NULL
                ORDER BY cm.created_at DESC
            """).fetchall()
            seen = set()
            for r in rows:
                uid = r["tg_id"]
                if uid in seen: 
                    continue
                seen.add(uid)
                username = None
                all_data = r["telegram_data"]
                try:
                    obj = json.loads(all_data)
                    # telegram JSON может содержать {"from": {"username": "..."}}
                    frm = obj.get("from") if isinstance(obj, dict) else None
                    if isinstance(frm, dict):
                        username = frm.get("username")
                except Exception:
                    pass

                ex = d.execute('SELECT 1 FROM user_extended WHERE tg_id=?', (uid,)).fetchone()
                if ex:
                    d.execute('UPDATE user_extended SET username=COALESCE(?, username), all_data=COALESCE(?, all_data) WHERE tg_id=?',
                              (username, all_data, uid))
                else:
                    d.execute('INSERT INTO user_extended (tg_id, username, all_data, create_dt) VALUES (?,?,?,CURRENT_TIMESTAMP)',
                              (uid, username, all_data))
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    # -------- visite_log (приближённо) --------
    if has_clients and table_exists(d, "visite_log"):
        print("Перенос visite_log ...")
        d.execute("BEGIN;")
        try:
            for row in s.execute("SELECT telegram_id, updated_at, created_at FROM clients WHERE telegram_id IS NOT NULL"):
                uid = row["telegram_id"]
                dt  = row["updated_at"] or row["created_at"]
                if not dt: 
                    continue
                visit_date = str(dt).split(' ')[0]
                # вставка/инкремент
                d.execute('INSERT OR IGNORE INTO visite_log (user_tg_id, visit_date, visit_count) VALUES (?,?,?)',
                          (uid, visit_date, 1))
                d.execute('UPDATE visite_log SET visit_count=visit_count+1 WHERE user_tg_id=? AND visit_date=?',
                          (uid, visit_date))
            d.execute("COMMIT;")
        except Exception:
            d.execute("ROLLBACK;"); raise

    src.close(); dst.close()
    print("Готово. Расширенный перенос завершён.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python transfer_full_finsky_to_tgbase.py /path/to/finsky.sqlite /path/to/tg_base.sqlite")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
