"""
Migrate data from legacy Finsky SQLite database into our SQLite database.

Run the script with paths to the source and target databases::

    python migrate_finsky.py --source finsky.db --target our.db

Clients lacking names are still imported; their Telegram ID is used as a fallback name.
"""

import argparse
import json
import sqlite3
from typing import Any, Dict


def migrate_clients(src: sqlite3.Connection, dst: sqlite3.Connection) -> Dict[int, sqlite3.Row]:
    """Import clients and basic profile info."""
    clients = src.execute("SELECT * FROM clients").fetchall()
    by_id: Dict[int, Dict[str, Any]] = {}
    for c in clients:
        tg_id = c["telegram_id"] or c["id"]
        client_record = dict(c)
        client_record["tg_id"] = tg_id
        by_id[c["id"]] = client_record
        full_name = " ".join(filter(None, [c["name"], c["surname"], c["patronymic"]]))
        if not full_name:
            # some legacy rows lack a name; use Telegram ID to keep record
            full_name = str(tg_id)
        dst.execute(
            "INSERT OR IGNORE INTO users (tg_id, name, phone, create_dt) VALUES (?, ?, ?, ?)",
            (tg_id, full_name, c["phone"], c["created_at"]),
        )

        extra = {
            "surname": c["surname"],
            "patronymic": c["patronymic"],
            "comment": c["comment"],
            "status": c["status"],
            "menu_state": c["menu_state"],
            "is_tester": c["is_tester"],
            "last_action_at": c["last_action_at"],
            "started_at": c["started_at"],
        }
        extra = {k: v for k, v in extra.items() if v is not None}
        if extra:
            dst.execute(
                "INSERT OR IGNORE INTO user_extended (tg_id, all_data) VALUES (?, ?)",
                (tg_id, json.dumps(extra, ensure_ascii=False)),
            )
    return by_id


def migrate_chat_messages(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    clients_by_id: Dict[int, sqlite3.Row],
) -> None:
    chats = {row["id"]: row for row in src.execute("SELECT * FROM chats")}
    messages = src.execute("SELECT * FROM chat_messages").fetchall()

    cols = {r["name"] for r in dst.execute("PRAGMA table_info('participant_messages')")}
    has_is_answer = "is_answer" in cols
    has_is_deleted = "is_deleted" in cols

    for m in messages:
        chat = chats.get(m["chat_id"])
        if not chat:
            continue
        client = clients_by_id.get(chat["client_id"])
        if not client:
            continue
        user_tg_id = client["tg_id"]
        sender = "user" if m["from_client"] else "admin"

        media_payload: Dict[str, Any] = {}
        if m["telegram_id"]:
            media_payload["telegram_id"] = m["telegram_id"]
        if m["files"]:
            try:
                media_payload["files"] = json.loads(m["files"])
            except Exception:
                media_payload["files"] = m["files"]
        if m["telegram_data"]:
            try:
                media_payload["telegram_data"] = json.loads(m["telegram_data"])
            except Exception:
                media_payload["telegram_data"] = m["telegram_data"]
        media_json = json.dumps(media_payload, ensure_ascii=False) if media_payload else None

        columns = ["user_tg_id", "sender", "text", "buttons", "media", "timestamp"]
        values = [user_tg_id, sender, m["text"], None, media_json, m["created_at"]]
        if has_is_answer:
            columns.append("is_answer")
            values.append(0 if m["from_client"] else 1)
        if has_is_deleted:
            columns.append("is_deleted")
            values.append(0)
        sql = f"INSERT INTO participant_messages ({', '.join(columns)}) VALUES ({', '.join(['?']*len(values))})"
        dst.execute(sql, values)


def migrate_support_requests(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    clients_by_id: Dict[int, sqlite3.Row],
) -> None:
    requests = src.execute("SELECT * FROM support_requests").fetchall()
    for r in requests:
        client = clients_by_id.get(r["client_id"])
        if not client:
            continue
        tg_id = client["tg_id"]
        dst.execute(
            "INSERT OR IGNORE INTO questions (id, user_tg_id, text, type, status, create_dt) VALUES (?, ?, ?, 'support', 'imported', ?)",
            (r["id"], tg_id, r["message"], r["created_at"]),
        )
        dst.execute(
            "INSERT OR IGNORE INTO question_messages (id, question_id, sender, text, is_answer, timestamp) VALUES (?, ?, 'user', ?, 0, ?)",
            (r["id"], r["id"], r["message"], r["created_at"]),
        )


def migrate_newsletters(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    letters = src.execute("SELECT * FROM newsletters").fetchall()
    for n in letters:
        schedule_dt = n["time"] or n["created_at"]
        # use beginning of newsletter text as its name instead of generic placeholder
        raw_text = (n["content"] or "").strip()
        first_line = raw_text.splitlines()[0] if raw_text else ""
        name = first_line[:50]  # keep names short for readability
        dst.execute(
            "INSERT OR IGNORE INTO scheduled_messages (name, content, schedule_dt, status, media, create_dt) VALUES (?, ?, ?, ?, ?, ?)",
            (name, n["content"], schedule_dt, n["status"], n["image"], n["created_at"]),
        )


def migrate_game_ratings(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    clients_by_id: Dict[int, sqlite3.Row],
) -> None:
    ratings = src.execute("SELECT * FROM game_ratings").fetchall()
    if not ratings:
        return
    times = [r["created_at"] for r in ratings if r["created_at"]]
    start = min(times) if times else None
    end = max(times) if times else None
    dst.execute(
        "INSERT INTO prize_draws (title, start_date, end_date, status, create_dt) VALUES (?, ?, ?, 'completed', ?)",
        ("Imported tournament", start, end, start),
    )
    draw_id = dst.execute("SELECT last_insert_rowid()").fetchone()[0]
    dst.execute(
        "INSERT INTO prize_draw_stages (draw_id, name, description, winners_count, order_index, create_dt) VALUES (?, 'Ratings', 'Imported from finsky.sql', 0, 0, ?)",
        (draw_id, start),
    )
    stage_id = dst.execute("SELECT last_insert_rowid()").fetchone()[0]

    for r in ratings:
        client = clients_by_id.get(r["client_id"])
        if not client:
            continue
        full_name = " ".join(
            filter(None, [client["name"], client["surname"], client["patronymic"]])
        ) or str(client["tg_id"])
        dst.execute(
            "INSERT OR IGNORE INTO prize_draw_winners (stage_id, user_tg_id, receipt_id, winner_name, create_dt) VALUES (?, ?, ?, ?, ?)",
            (stage_id, client["tg_id"], r["rating"], full_name, r["created_at"]),
        )


def migrate(source_path: str, target_path: str) -> None:
    src = sqlite3.connect(source_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(target_path)
    dst.row_factory = sqlite3.Row
    try:
        with dst:
            clients = migrate_clients(src, dst)
            migrate_chat_messages(src, dst, clients)
            migrate_support_requests(src, dst, clients)
            migrate_newsletters(src, dst)
            migrate_game_ratings(src, dst, clients)
    finally:
        src.close()
        dst.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate data from Finsky SQLite database."
    )
    parser.add_argument("--source", required=True, help="Path to source SQLite database")
    parser.add_argument("--target", required=True, help="Path to target SQLite database")
    args = parser.parse_args()
    migrate(args.source, args.target)


if __name__ == "__main__":
    main()

