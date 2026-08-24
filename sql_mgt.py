from __future__ import annotations

import aiosqlite
import asyncio
import os
import datetime
import sqlite3
import json
import logging

from typing import Iterable, Dict, Any, Optional, List, Tuple

from keys import DB_NAME
import receipt_validation


global_objects = None
db_name = None
logger = logging.getLogger(__name__)

_TABLE_SCHEME_CACHE: dict[str, str] | None = None


def _load_table_shem() -> dict[str, str]:
    global _TABLE_SCHEME_CACHE
    if _TABLE_SCHEME_CACHE is not None:
        return _TABLE_SCHEME_CACHE

    current_directory = os.path.dirname(os.path.abspath(__file__))
    table_shem_path = os.path.join(current_directory, "table_shem.json")
    with open(table_shem_path, "rb") as table_shem_file:
        _TABLE_SCHEME_CACHE = json.load(table_shem_file)
    return _TABLE_SCHEME_CACHE


def get_table_schema_sql(table_name: str) -> str | None:
    """Return the CREATE TABLE statement body for the given table."""

    table_shem = _load_table_shem()
    return table_shem.get(table_name)


def _split_schema_parts(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        if char == "," and depth == 0:
            piece = "".join(current).strip()
            if piece:
                parts.append(piece)
            current = []
            continue
        current.append(char)
    trailing = "".join(current).strip()
    if trailing:
        parts.append(trailing)
    return parts


def _parse_table_schema(create_execute_script: str) -> list[tuple[str, str]]:
    body = create_execute_script.split("(", 1)[1].rsplit(")", 1)[0]
    parts = _split_schema_parts(body)
    columns: list[tuple[str, str]] = []
    for part in parts:
        upper = part.upper()
        if upper.startswith("UNIQUE") or upper.startswith("PRIMARY KEY") or upper.startswith("FOREIGN KEY"):
            continue
        tokens = part.split()
        if not tokens:
            continue
        column_name = tokens[0]
        column_type = " ".join(tokens[1:])
        columns.append((column_name, column_type))
    return columns


def get_table_schema_columns(table_name: str) -> list[tuple[str, str]]:
    """Return ordered column definitions for the requested table."""

    create_execute_script = get_table_schema_sql(table_name)
    if not create_execute_script:
        return []
    return _parse_table_schema(create_execute_script)

RECEIPT_COLUMNS_ORDER: list[tuple[str, str]] = [
    ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    ("number", "TEXT"),
    ("date", "DATE"),
    ("amount", "REAL"),
    ("user_tg_id", "INTEGER"),
    ("draw_id", "INTEGER"),
    ("message_id", "INTEGER"),
    ("qr", "TEXT"),
    ("file_path", "TEXT"),
    ("status", "TEXT DEFAULT 'не подтвержден'"),
    ("comment", "TEXT"),
    ("create_dt", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
]

RECEIPT_COLUMN_NAMES: tuple[str, ...] = tuple(col for col, _ in RECEIPT_COLUMNS_ORDER)

def init_object(global_objects_inp):
    global global_objects
    global db_name

    global_objects = global_objects_inp

    #print('dirname -> ', global_objects.settings_bot['run_directory'])
    db_name = f"{global_objects.settings_bot['run_directory']}/{DB_NAME}"
    ensure_receipt_comment_column_sync()


''' Созадём таблицы '''
# ==================================================================
async def create_table(conn, create_execute_script):
    cursor = await conn.cursor()
    await cursor.execute('CREATE TABLE IF NOT EXISTS ' + create_execute_script)
    await conn.commit()

async def get_table_info(conn, table_name):
    cursor = await conn.cursor()
    await cursor.execute(f"PRAGMA table_info({table_name});")
    columns_info = await cursor.fetchall()
    return {col[1]: col[2] for col in columns_info}  # возвращаем словарь {column_name: column_type}

async def compare_schemas(existing_schema, new_schema):
    existing_columns = set(existing_schema.keys())
    new_columns = set(new_schema.keys())

    # Определяем, какие столбцы добавить, какие удалить
    columns_to_add = new_columns - existing_columns
    columns_to_remove = existing_columns - new_columns
    return columns_to_add, columns_to_remove

async def update_table(conn, table_name, new_schema):
    existing_schema = await get_table_info(conn, table_name)
    columns_to_add, columns_to_remove = await compare_schemas(existing_schema, new_schema)

    # Добавляем новые столбцы
    if columns_to_add:
        for column in columns_to_add:
            column_type = new_schema[column]
            await conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")
        await conn.commit()

    # Удаляем лишние столбцы (создание новой таблицы)
    if columns_to_remove:
        await recreate_table_with_new_schema(conn, table_name, new_schema, existing_schema)

async def recreate_table_with_new_schema(conn, table_name, new_schema, existing_schema):
    cursor = await conn.cursor()

    # Создаем временную таблицу с новой схемой
    columns_definition = ', '.join([f"{col} {col_type}" for col, col_type in new_schema.items()])
    # Удаляем временную таблицу, если осталась после предыдущей неудачной миграции
    await cursor.execute(f"DROP TABLE IF EXISTS {table_name}_new")
    await cursor.execute(f"CREATE TABLE {table_name}_new ({columns_definition})")
    await conn.commit()

    # Копируем данные в новую таблицу, соответствующие существующим столбцам
    old_columns = ', '.join([col for col in new_schema.keys() if col in existing_schema.keys()])
    if old_columns:
        await cursor.execute(
            f"INSERT INTO {table_name}_new ({old_columns}) SELECT {old_columns} FROM {table_name}"
        )
        await conn.commit()

    # Удаляем старую таблицу и переименовываем новую
    await cursor.execute(f"DROP TABLE {table_name}")
    await cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")
    await conn.commit()

async def create_or_update_tables(conn, schema_dict):
    # Однократная миграция prize_draw_rules.draw_id -> stage_id — должна отработать
    # до того, как generic-механизм ниже увидит несовпадающие по имени столбцы и
    # молча пересоздаст таблицу без переноса данных (см. CLAUDE.md / раздел 4.2 ТЗ).
    if "prize_draw_rules" in schema_dict:
        await migrate_prize_draw_rules_draw_to_stage(conn)
    # Однократная миграция prize_draws.{start_date,end_date,status,auto_validation_enabled}
    # -> те же поля на prize_draw_stages (акция становится безданным контейнером, "активным"
    # может быть только ОДИН этап во всей системе). Тоже должна отработать до generic-сброса.
    if "prize_draws" in schema_dict and "prize_draw_stages" in schema_dict:
        await migrate_draw_fields_to_stage(conn)

    for table_name, create_execute_script in schema_dict.items():
        column_defs = dict(_parse_table_schema(create_execute_script))

        # Проверяем, существует ли таблица
        cursor = await conn.cursor()
        await cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        table_exists = await cursor.fetchone()

        if table_exists:
            # Обновляем таблицу, если она существует
            await update_table(conn, table_name, column_defs)
        else:
            # Создаем таблицу, если её нет
            await create_table(conn, create_execute_script)


async def migrate_prize_draw_rules_draw_to_stage(conn) -> None:
    """Одноразовая миграция prize_draw_rules.draw_id -> stage_id.

    Копирует каждое старое привязанное к акции правило на КАЖДЫЙ существующий этап
    этой акции — воспроизводя прежнее поведение "правило общее на акцию" (этапы
    раньше вообще не влияли на проверку чека). Акция без единого этапа — правило
    физически некуда привязать, строка не переносится, в лог пишется предупреждение
    (не блокирует запуск). Идемпотентно: повторный вызов после успешной миграции —
    no-op. Атомарно: явная транзакция, откат при любой ошибке не оставляет БД в
    промежуточном состоянии. См. TZ_GUARANTEED_PRIZE_STAGE_TYPES.md, раздел 4.2.
    """
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='prize_draw_rules'"
    )
    if not await cursor.fetchone():
        # Таблицы ещё нет вовсе — её создаст обычный create_table() уже по новой схеме.
        return

    existing_columns = await get_table_info(conn, "prize_draw_rules")
    if "stage_id" in existing_columns:
        # Уже мигрировано (или свежая установка) — идемпотентный выход.
        return
    if "draw_id" not in existing_columns:
        # Неожиданная схема без draw_id и без stage_id — нечего мигрировать.
        return

    await conn.execute("BEGIN IMMEDIATE")
    try:
        await cursor.execute(
            "SELECT id, draw_id, title, sku_code, aliases, min_quantity, is_active, create_dt "
            "FROM prize_draw_rules"
        )
        old_rows = await cursor.fetchall()

        new_rows: list[tuple] = []
        skipped = 0
        for _old_id, draw_id, title, sku_code, aliases, min_quantity, is_active, create_dt in old_rows:
            await cursor.execute(
                "SELECT id FROM prize_draw_stages WHERE draw_id = ? ORDER BY id", (draw_id,)
            )
            stage_ids = [row[0] for row in await cursor.fetchall()]
            if not stage_ids:
                skipped += 1
                logger.warning(
                    "migrate_prize_draw_rules_draw_to_stage: у акции draw_id=%s нет ни одного "
                    "этапа — правило '%s' (id=%s) НЕ перенесено, требуется ручной просмотр",
                    draw_id, title, _old_id,
                )
                continue
            for stage_id in stage_ids:
                new_rows.append(
                    (stage_id, title, sku_code, aliases, min_quantity, is_active, create_dt)
                )

        new_schema_sql = get_table_schema_sql("prize_draw_rules")
        columns_definition = ", ".join(
            f"{col} {col_type}" for col, col_type in _parse_table_schema(new_schema_sql)
        )
        await cursor.execute("DROP TABLE IF EXISTS prize_draw_rules_migrating_new")
        await cursor.execute(f"CREATE TABLE prize_draw_rules_migrating_new ({columns_definition})")
        for values in new_rows:
            await cursor.execute(
                "INSERT INTO prize_draw_rules_migrating_new "
                "(stage_id, title, sku_code, aliases, min_quantity, is_active, create_dt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )
        await cursor.execute("DROP TABLE prize_draw_rules")
        await cursor.execute(
            "ALTER TABLE prize_draw_rules_migrating_new RENAME TO prize_draw_rules"
        )
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise

    logger.info(
        "migrate_prize_draw_rules_draw_to_stage: перенесено %s старых правил в %s "
        "новых строк по этапам (пропущено без этапов: %s)",
        len(old_rows), len(new_rows), skipped,
    )


async def migrate_draw_fields_to_stage(conn) -> None:
    """Одноразовая миграция: prize_draws.{start_date,end_date,status,auto_validation_enabled}
    переезжают на prize_draw_stages — акция становится безданным контейнером (просто title),
    "активным" может быть только ОДИН этап во всей системе (глобальная эксклюзивность).

    Копирует даты/автовалидацию на ВСЕ этапы своей акции (они действовали одинаково на всю
    акцию раньше). Статус распределяется иначе: только ПЕРВЫЙ этап акции (по order_index)
    получает старый статус акции, остальные этапы той же акции получают 'upcoming' — у старой
    модели не было понятия "статус этапа", поэтому не из чего его вывести для остальных.
    Затем — обязательный проход глобальной дедупликации: если после переноса 'active' оказался
    более чем у одного этапа (в разных акциях бывший overlap-чек допускал максимум одну active
    акцию единовременно, но это не гарантия на любых исторических данных) — оставляем только
    ОДИН (наименьший id), остальные понижаем до 'upcoming'. Акция без единого этапа — даты/
    статус физически некуда перенести, в лог пишется предупреждение, данные теряются.
    Атомарно (BEGIN IMMEDIATE/commit/rollback), идемпотентна.
    """
    cursor = await conn.cursor()
    draws_schema = await get_table_info(conn, "prize_draws")
    if "start_date" not in draws_schema:
        return  # уже мигрировано (или свежая установка)

    await conn.execute("BEGIN IMMEDIATE")
    try:
        stages_schema = await get_table_info(conn, "prize_draw_stages")
        for col, col_type in (
            ("start_date", "DATE"),
            ("end_date", "DATE"),
            ("status", "TEXT NOT NULL DEFAULT 'upcoming'"),
            ("auto_validation_enabled", "BOOLEAN DEFAULT 1"),
        ):
            if col not in stages_schema:
                await cursor.execute(
                    f"ALTER TABLE prize_draw_stages ADD COLUMN {col} {col_type}"
                )

        await cursor.execute(
            "SELECT id, start_date, end_date, status, auto_validation_enabled FROM prize_draws"
        )
        old_draws = await cursor.fetchall()

        active_candidates: list[int] = []
        skipped = 0
        for draw_id, start_date, end_date, status, auto_val in old_draws:
            await cursor.execute(
                "SELECT id FROM prize_draw_stages WHERE draw_id = ? ORDER BY order_index, id",
                (draw_id,),
            )
            stage_ids = [row[0] for row in await cursor.fetchall()]
            if not stage_ids:
                skipped += 1
                logger.warning(
                    "migrate_draw_fields_to_stage: у акции draw_id=%s нет ни одного этапа — "
                    "даты/статус/автовалидация НЕ перенесены, требуется ручной просмотр",
                    draw_id,
                )
                continue
            for stage_id in stage_ids:
                await cursor.execute(
                    "UPDATE prize_draw_stages SET start_date = ?, end_date = ?, "
                    "auto_validation_enabled = ? WHERE id = ?",
                    (start_date, end_date, auto_val, stage_id),
                )
            first_stage_id = stage_ids[0]
            stage_status = status if status else "upcoming"
            await cursor.execute(
                "UPDATE prize_draw_stages SET status = ? WHERE id = ?",
                (stage_status, first_stage_id),
            )
            if stage_status == "active":
                active_candidates.append(first_stage_id)

        # Глобальная эксклюзивность: активным может быть только один этап во всей системе.
        if len(active_candidates) > 1:
            keep = min(active_candidates)
            for stage_id in active_candidates:
                if stage_id != keep:
                    await cursor.execute(
                        "UPDATE prize_draw_stages SET status = 'upcoming' WHERE id = ?",
                        (stage_id,),
                    )
            logger.warning(
                "migrate_draw_fields_to_stage: найдено %s одновременно 'active' акций — "
                "оставлен только этап id=%s, остальные понижены до 'upcoming'",
                len(active_candidates), keep,
            )

        new_schema_sql = get_table_schema_sql("prize_draws")
        columns_definition = ", ".join(
            f"{col} {col_type}" for col, col_type in _parse_table_schema(new_schema_sql)
        )
        await cursor.execute("DROP TABLE IF EXISTS prize_draws_migrating_new")
        await cursor.execute(f"CREATE TABLE prize_draws_migrating_new ({columns_definition})")
        await cursor.execute(
            "INSERT INTO prize_draws_migrating_new (id, title, create_dt) "
            "SELECT id, title, create_dt FROM prize_draws"
        )
        await cursor.execute("DROP TABLE prize_draws")
        await cursor.execute("ALTER TABLE prize_draws_migrating_new RENAME TO prize_draws")
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise

    logger.info(
        "migrate_draw_fields_to_stage: перенесено %s акций на этапы (пропущено без этапов: %s)",
        len(old_draws) - skipped, skipped,
    )


async def create_db():
    table_shem = _load_table_shem()

    async with aiosqlite.connect(db_name) as conn:
        # Создаем таблицу
        #for keys in table_shem.keys():
        #    await create_or_update_tables(conn, table_shem.get(keys))
        await create_or_update_tables(conn, table_shem)
# ==================================================================


''' Декоратор подключения к базе данных '''
def with_connection(func):
    async def wrapper(*args, **kwargs):
        # Проверяем, есть ли параметр conn в аргументах функции
        conn = kwargs.get('conn')
        close_conn = False
        
        # Если conn не передан, подключаемся к базе данных
        if conn is None:
            conn = await aiosqlite.connect(db_name)
            close_conn = True

        #print('db_name -> ', db_name)

        kwargs['conn'] = conn

        try:
            # Вызываем оригинальную функцию с подключением к базе данных
            result = await func(*args, **kwargs)
        finally:
            # Закрываем подключение после выполнения функции
            if close_conn:
                await conn.close()
        
        return result

    return wrapper


''' Декоратор подключения к базе данных не async '''
def with_connection_def(func):
    def wrapper(*args, **kwargs):
        # Проверяем, есть ли параметр conn в аргументах функции
        conn = kwargs.get('conn')
        close_conn = False
        
        # Если conn не передан, подключаемся к базе данных
        if conn is None:
            conn = sqlite3.connect(db_name)
            close_conn = True

        #print('db_name def -> ', db_name)

        try:
            kwargs['conn'] = conn
            # Вызываем оригинальную функцию с подключением к базе данных
            result = func(*args, **kwargs)
        finally:
            # Закрываем подключение после выполнения функции
            if close_conn:
                #if kwargs.get('conn') is None:
                conn.close()
        
        return result

    return wrapper


@with_connection
async def insert_user(message, conn=None):
    # создаём доп поля
    await insert_user_extended(message)
    await create_user_settings(message)

    cursor = await conn.cursor()

    # Проверка наличия записи с указанным tg_id
    await cursor.execute('SELECT COUNT(*) FROM users WHERE tg_id = ?', (message.chat.id,))
    count = await cursor.fetchone()
    
    if count[0] == 0:
        # Записи с tg_id нет, выполняем вставку
        await cursor.execute('INSERT INTO users (tg_id, name) VALUES (?, ?)', (message.chat.id, message.from_user.full_name))
        await conn.commit()


@with_connection
async def insert_user_extended(message, conn=None):
    cursor = await conn.cursor()

    # Проверка наличия записи с указанным tg_id
    await cursor.execute('SELECT COUNT(*) FROM user_extended WHERE tg_id = ?', (message.chat.id,))
    count = await cursor.fetchone()
    
    if count[0] == 0:
        # Записи с tg_id нет, выполняем вставку
        await cursor.execute('INSERT INTO user_extended (tg_id, username, all_data) VALUES (?, ?, ?)', (
            message.chat.id, 
            message.from_user.username,
            str(dict(message))
        ))
        await conn.commit()


@with_connection
async def ins_up_user_params(user_tg_id, last_message_id=None, last_media_message_list=None, conn=None):
    cursor = await conn.cursor()

    # Формируем список столбцов и соответствующих значений
    columns = []
    values = []

    if last_message_id is not None:
        columns.append('last_message_id')
        values.append(last_message_id)

    if last_media_message_list is not None:
        columns.append('last_media_message_list')
        values.append(', '.join([str(l) for l in last_media_message_list]))

    # Формируем часть SQL-запроса с учетом переданных параметров
    columns_str = ', '.join(columns)
    values_str = ', '.join(['?'] * len(values))
    params = ' = ?, '.join(columns) + ' = ?'

    # Пытаемся вставить новую запись
    await cursor.execute(f'INSERT OR IGNORE INTO user_params (user_tg_id, {columns_str}) VALUES (?, {values_str})',
                         (user_tg_id, *values))

    # Теперь обновляем значения, если запись уже существует
    await cursor.execute(f'UPDATE user_params SET {params} WHERE user_tg_id = ?',
                         (*values, user_tg_id))
    await conn.commit()


@with_connection
async def get_user_params(user_tg_id, conn=None):
    cursor = await conn.cursor()

    # Выполняем запрос SELECT для получения данных
    await cursor.execute('SELECT * FROM user_params WHERE user_tg_id = ?', (user_tg_id,))

    # Извлекаем одну запись (или None, если запись не найдена)
    result = await cursor.fetchone()

    return result


@with_connection
async def get_last_media_and_set_next(user_tg_id, conn=None):
    cursor = await conn.cursor()
    table_name = 'last_media'

    # Создать новую запись
    await cursor.execute(f"INSERT INTO {table_name} (user_tg_id) VALUES ('{user_tg_id}');")
    # Получить новую последнюю запись в таблице
    await cursor.execute(f'SELECT * FROM {table_name} ORDER BY media_id DESC LIMIT 1;')
    new_last_record = await cursor.fetchone()

    await conn.commit()

    next_media_id = list(new_last_record)[0]

    return next_media_id


''' Логи посещения '''
# ==================================================================
@with_connection
async def add_visit(user_tg_id, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"INSERT OR IGNORE INTO visite_log (user_tg_id, visit_date, visit_count) \
                            VALUES ({user_tg_id}, date('now'), 0);")
    await cursor.execute(f"UPDATE visite_log \
                            SET visit_count = visit_count + 1 \
                            WHERE user_tg_id = {user_tg_id} AND visit_date = date('now');")
    await conn.commit()


@with_connection
async def get_visit(day_count, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f'''SELECT
    strftime('%Y-%m-%d', visit_date) AS visit_date,
    SUM(visit_count) AS total_visits_per_day
    FROM
    visite_log
    WHERE
    visit_date BETWEEN date('now', '-{day_count - 1} days') AND date('now')
    GROUP BY
    visit_date
    ORDER BY
    visit_date;''')
    visit_list = await cursor.fetchall()
    await conn.commit()
    return visit_list


@with_connection
async def get_users_per_day(day_count, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f'''SELECT
    strftime('%Y-%m-%d', visit_date) AS visit_date,
    COUNT(DISTINCT user_tg_id) AS users_per_day
    FROM
    visite_log
    WHERE
    visit_date BETWEEN date('now', '-{day_count - 1} days') AND date('now')
    GROUP BY
    visit_date
    ORDER BY
    visit_date;''')
    users_list = await cursor.fetchall()
    await conn.commit()
    return users_list
# ==================================================================


''' получение и добавление параметров '''
# ==================================================================
@with_connection
async def set_param(user_tg_id, param_name, param_value, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"INSERT OR IGNORE INTO params (user_tg_id, param_name, value) \
                            VALUES ({user_tg_id}, '{param_name}', '{param_value}');")
    await cursor.execute(f"UPDATE params \
                            SET value = '{param_value}' \
                            WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}';")
    await conn.commit()


@with_connection
async def get_param(user_tg_id, param_name, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT value FROM params WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}'")
    result = await cursor.fetchone()

    if not result: 
        return ''
    
    return_str = result[0]
    if len(return_str) > 0:
        if return_str[0] == ',':
            return_str = return_str[1:]
    return return_str


@with_connection
async def append_param_get_old(user_tg_id, param_name, param_value, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"INSERT OR IGNORE INTO params (user_tg_id, param_name, value) \
                            VALUES ({user_tg_id}, '{param_name}', '{param_value}');")
    await cursor.execute(f"UPDATE params \
                            SET value = value || ',{param_value}' \
                            WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}';")
    await cursor.execute(f"SELECT value FROM params WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}'")
    result = await cursor.fetchone()
    await conn.commit()

    if not result: 
        return ''
    return_str = result[0]
    if return_str[0] == ',':
        return_str = return_str[1:]
    return return_str
# ==================================================================


''' Работа с админами '''
# ==================================================================
@with_connection
async def add_admin(user_tg_id:int, user_id_add:int, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"INSERT OR IGNORE INTO admins (user_tg_id, user_id_add) \
                            VALUES ({user_tg_id}, {user_id_add});")
    await conn.commit()

@with_connection
async def delete_admin(user_tg_id:int, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"DELETE FROM admins WHERE user_tg_id = {user_tg_id};")
    await conn.commit()


@with_connection
async def get_admins(conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f'''SELECT users.tg_id, users.name
        FROM users
        INNER JOIN admins ON users.tg_id = admins.user_tg_id;''')
    admin_list = list(await cursor.fetchall())
    await conn.commit()

    return admin_list


@with_connection
async def get_admins_id(conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f'''SELECT user_tg_id FROM admins;''')
    admin_list = list(await cursor.fetchall())
    await conn.commit()

    return admin_list


async def upload_admins(new_admin_list):
    admins = await get_admins_id()

    if len(admins) == 0: 
        for new_admin in new_admin_list: 
            try:
                await add_admin(new_admin, new_admin)
            except Exception as e:
                print(f'При попытке добавить админов при запуске произошла ошибка {e}')


@with_connection
async def get_admins_by_rule_async(rule:str, conn=None):
    cursor = await conn.cursor()
    #await cursor.execute(f"SELECT user_tg_id FROM user_rule WHERE user_tg_id = LIKE '%{rule}%'")
    await cursor.execute(f'''
        SELECT *
        FROM users
        INNER JOIN user_rule ON users.tg_id = user_rule.user_tg_id
        WHERE user_rule.rule LIKE '%{rule}%';
    ''')
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


@with_connection_def
def get_admins_by_rule(rule:str, conn=None):
    cursor = conn.cursor()
    #await cursor.execute(f"SELECT user_tg_id FROM user_rule WHERE user_tg_id = LIKE '%{rule}%'")
    cursor.execute(f'''
        SELECT *
        FROM users
        INNER JOIN user_rule ON users.tg_id = user_rule.user_tg_id
        WHERE user_rule.rule LIKE '%{rule}%';
    ''')
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


@with_connection
async def create_invite_admin_key(user_tg_id:int, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"DELETE FROM admin_invite WHERE create_dt < datetime('now', '-1 hour');")
    await cursor.execute(f"INSERT INTO admin_invite (user_create_id) VALUES ('{user_tg_id}');")
    new_record_id = cursor.lastrowid
    await cursor.execute("SELECT random_key FROM admin_invite WHERE ROWID=?", (new_record_id,))
    autoincrement_key_value = await cursor.fetchone()
    await conn.commit()

    return autoincrement_key_value[0]


@with_connection
async def is_normal_invite_admin_key(key:str, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"DELETE FROM admin_invite WHERE create_dt < datetime('now', '-1 hour');")
    await cursor.execute(f"SELECT user_create_id FROM admin_invite WHERE random_key = '{key}';")
    result = await cursor.fetchone()
    await cursor.execute(f"DELETE FROM admin_invite WHERE random_key = '{key}';")
    await conn.commit()

    if not result:
        return result

    return result[0]

# ==================================================================


''' Работа с юзерами '''
# ==================================================================
@with_connection
async def get_user_async(tg_id:int, conn=None):
    cursor = await conn.cursor()
    #await cursor.execute(f"SELECT user_tg_id FROM user_rule WHERE user_tg_id = LIKE '%{rule}%'")
    await cursor.execute(f'''
        SELECT *
        FROM users
        WHERE tg_id = {tg_id};
    ''')
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = await cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


@with_connection
async def update_user_async(chat_id: int, fields: dict, conn=None):
    # Обновляем поля (age_18 или phone) у пользователя
    # Например, для {"age_18": True}
    cursor = await conn.cursor()
    if "age_18" in fields:
        await cursor.execute(f'UPDATE users SET age_18 = {fields["age_18"]} WHERE tg_id = {chat_id}')
    if "phone" in fields:
        await cursor.execute(f'UPDATE users SET phone = {fields["phone"]} WHERE tg_id = {chat_id}')
    await conn.commit()
# ==================================================================



''' Работа заказами '''
# ==================================================================
@with_connection
async def get_last_order(conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM sales_header ORDER BY no DESC LIMIT 1;")
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = await cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


@with_connection
async def get_orders_lines(orders:list, conn=None):
    if len(orders) == 0:
        return None

    order_no_list = [f"'{order.get('no')}'" for order in orders]
    order_no_text = ", ".join(order_no_list)
    
    cursor = conn.cursor()
    query = f"SELECT * FROM sales_line WHERE sales_no IN ({order_no_text})"
    cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


@with_connection
async def update_is_paid_for(order_no, is_paid_for, conn=None):
    cursor = await conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE sales_header SET is_paid_for = ? WHERE no = '{order_no}'"

    # Выполнение запроса
    await cursor.execute(query, (int(is_paid_for), ))
    await conn.commit()


@with_connection
async def update_order_status_sql_async(order_no:str, status:str, conn=None):
    cursor = await conn.cursor()
    print('update_staus -> ', status, order_no)

    select_query = f"SELECT no FROM sales_header WHERE no = '{order_no}'"
    await cursor.execute(select_query)
    order_exists = await cursor.fetchone()

    # Выводим результат запроса в консоль
    print(f"Order exists check result for '{order_no}':", order_exists)

    # Формирование запроса на обновление записи
    query = f"UPDATE sales_header SET status = ? WHERE no = '{order_no}'"

    # Выполнение запроса
    await cursor.execute(query, (status,))
    await conn.commit()

    print(cursor.rowcount) 



@with_connection_def
def update_order_status_sql(order_no:str, status:str, conn=None):
    cursor = conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE sales_header SET status = '{status}' WHERE no = '{order_no}'"

    # Выполнение запроса
    cursor.execute(query)
    conn.commit()


@with_connection
async def get_cancel_orders(date_time_now=True, conn=None):
    cursor = await conn.cursor()
    if date_time_now:
        await cursor.execute(f"SELECT * FROM cancel_order WHERE cancel_order_dt < '{datetime.datetime.now()}';")
    else:
        await cursor.execute(f"SELECT * FROM cancel_order")
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    results = []
    for row in await cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


@with_connection
async def get_cancel_order(order_no, conn=None):
    cursor = await conn.cursor()
    query = f"SELECT * FROM cancel_order WHERE order_no = '{order_no}'"
    await cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = await cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


@with_connection
async def add_cancel_order(order_no:str, user_tg_id:int, chat_id:int, pyment_message_id:int, cancel_order_dt, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"DELETE FROM cancel_order WHERE order_no = '{order_no}';")
    await cursor.execute(f"""INSERT INTO cancel_order (order_no, user_tg_id, chat_id, pyment_message_id, cancel_order_dt) 
                            VALUES ('{order_no}', '{user_tg_id}', '{chat_id}', '{pyment_message_id}', '{cancel_order_dt}');""")

    await conn.commit()


@with_connection
async def delete_cancel_order(order_no:str, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"DELETE FROM cancel_order WHERE order_no = '{order_no}';")

    await conn.commit()


@with_connection
async def get_order(order_no, conn=None):
    cursor = await conn.cursor()
    query = f"SELECT * FROM sales_header WHERE no = '{order_no}'"
    await cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = await cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result
# ==================================================================


''' Работа с товарами '''
# ==================================================================
@with_connection
async def get_items_by_id(items_id:list, conn=None):
    items_id_list = [f"'{item_id}'" for item_id in items_id]
    items_id_text = ", ".join(items_id_list)

    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM item WHERE id IN ({items_id_text})")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = {}
    for row in await cursor.fetchall():
        item_dict = dict(zip(columns, row))
        results[item_dict.get('id')] = item_dict

    return results


@with_connection
async def subtract_amount_item(item_id, amount:int, conn=None):
    # вычитаем из товара число
    cursor = await conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE item SET quantity = quantity - {amount} WHERE id = '{item_id}'"

    # Выполнение запроса
    await cursor.execute(query)
    await conn.commit()
# ==================================================================


''' Работа с кошельком '''
# ==================================================================
def get_next_month_date(date_old):
    date_new:datetime.date = date_old

    month = date_new.month + 1
    year = date_new.year

    if date_new.day > 28:
        date_new = date_new.replace(day=1)
        month += 1

    if month > 12:
        year += 1
        month -= 12

    date_new = date_new.replace(month=month, year=year) 

    return date_new


@with_connection
async def init_wallet(conn=None):
    cursor = await conn.cursor()
    await cursor.execute("SELECT EXISTS (SELECT 1 FROM wallet_log)")
    exists = await cursor.fetchone()

    if exists[0]:
        return
    
    # если записи нет в базе, делаем нулевую запись
    pyment_date = get_next_month_date(datetime.date.today())
    await cursor.execute(f"INSERT INTO wallet_log (user_tg_id, type, code, description, balance, total_spent_month, total_spent, next_write_off_date) VALUES ('0', 'START', 'START', 'Запуск бота', 0, 0, 0, '{pyment_date}');")
    await conn.commit()


@with_connection_def
def get_wallet_data(conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = cursor.fetchone()
    if row:
        result = dict(zip(columns, row))
    else:
        result = None

    return result


@with_connection
async def get_wallet_data_asunc(conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = await cursor.fetchone()
    if row:
        result = dict(zip(columns, row))
    else:
        result = None

    return result


@with_connection
async def append_fill_wallet_line(user_tg_id: int, type_line: str, code:str, description: str, amount:float, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = await cursor.fetchone()
    result = dict(zip(columns, row))

    await cursor.execute(f"""INSERT INTO wallet_log (user_tg_id, type, code, description, balance, total_spent_month, total_spent, next_write_off_date) 
                         VALUES ('{user_tg_id}', 
                            '{type_line}', 
                            '{code}', 
                            '{description}', 
                            '{result['balance'] + amount}', 
                            '{result['total_spent_month']}',
                            '{result['total_spent']}',
                            '{result['next_write_off_date']}');
                        """)
    await conn.commit()

    await cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = await cursor.fetchone()
    result = dict(zip(columns, row))
    return result


@with_connection
async def append_order_wallet_line(user_tg_id: int, type_line: str, code:str, description: str, amount_order:float, deduction_procent: float, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = await cursor.fetchone()
    result = dict(zip(columns, row))

    await cursor.execute(f"""INSERT INTO wallet_log (user_tg_id, type, code, description, balance, total_spent_month, total_spent, next_write_off_date) 
                         VALUES ('{user_tg_id}', 
                            '{type_line}', 
                            '{code}', 
                            '{description}', 
                            '{result['balance'] - deduction_procent}', 
                            '{result['total_spent_month'] + amount_order}',
                            '{result['total_spent'] + amount_order}',
                            '{result['next_write_off_date']}');
                        """)
    await conn.commit()

    await cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = await cursor.fetchone()
    result = dict(zip(columns, row))
    return result
# ==================================================================


''' Настройки пользователя '''
# ==================================================================
@with_connection
async def create_user_settings(message, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"INSERT OR IGNORE INTO user_settings (tg_id, subscription) \
                            VALUES ({message.chat.id}, {1});")
    await conn.commit()


@with_connection
async def user_is_subscript(user_tg_id: int, conn=None):
    cursor = await conn.cursor()
    query = f"SELECT subscription FROM user_settings WHERE tg_id = '{user_tg_id}'"
    await cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = await cursor.fetchone()
    if row == None:
        return True
    
    result = dict(zip(columns, row)) if row else None

    return result['subscription'] == 1


@with_connection
async def update_user_subscription(user_tg_id: int, subscription:bool, conn=None):
    cursor = await conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE user_settings SET subscription = '{int(subscription)}' WHERE tg_id = '{user_tg_id}'"

    # Выполнение запроса
    await cursor.execute(query)
    await conn.commit()


@with_connection
async def get_all_subscriptions_id(conn=None):
    cursor = await conn.cursor()

    query = f"SELECT tg_id FROM users"
    await cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    tg_id_list = []
    for row in await cursor.fetchall():
        row_data = dict(zip(columns, row))
        tg_id_list.append(row_data.get('tg_id'))

    subscript_user_list = []
    for tg_id in tg_id_list:
        if await user_is_subscript(tg_id, conn=conn):
            subscript_user_list.append(tg_id)

    return subscript_user_list

# ==================================================================


''' Сайт '''
# ==================================================================
@with_connection
async def append_additional_fields(sales_no:str, additional_fields:dict, conn:None = None):
    cursor = await conn.cursor()

    values = ', '.join(['?'] * 4)
    query = f'''INSERT INTO additional_field (sales_no, field_name, field_description, value) 
        VALUES ({values})'''

    additional_fields_list = []
    for additional_field_key in additional_fields.keys():
        additional_fields_list.append({
            'sales_no': sales_no,
            'field_name': additional_field_key,
            'field_description': additional_fields[additional_field_key]['description'], 
            'value': additional_fields[additional_field_key]['value'],
        })

    if len(additional_fields_list) < 1:
        return 
    
    # Вставляем данные из списка
    for data in additional_fields_list:
        await cursor.execute(query, tuple(data.values()))

    await conn.commit()
# ==================================================================


def create_db_file():
    # Проверяем, существует ли файл в исходном каталоге
    if not os.path.exists(db_name):
        # Если файл не существует, копируем его
        table_shem = _load_table_shem()
        
        import sqlite3

        with sqlite3.connect(db_name) as conn:
            # Создаем таблицу
            for keys in table_shem.keys():
                cursor = conn.cursor()
                cursor.execute('CREATE TABLE IF NOT EXISTS ' + table_shem.get(keys))
                conn.commit()


async def main():
    # Открываем соединение с базой данных
    async with aiosqlite.connect("example.sqlite") as conn:
        # Создаем таблицу
        await create_or_update_tables(conn)


if __name__ == "__main__":
    # Запускаем асинхронный код
    #asyncio.run(main())
    db_name = '../tg_base.sqlite'
    asyncio.run(create_db())
















@with_connection
async def add_participant_message(
    user_tg_id: int,
    sender: str,
    text: Optional[str] = None,
    is_answer: bool = False,
    buttons: Optional[List[Dict[str, Any]]] = None,
    media: Optional[List[Dict[str, Any]]] = None,
    timestamp: Optional[datetime.datetime] = None,
    conn=None,
) -> int:
    """
    Сохраняет одно сообщение в participant_messages,
    вместе с опциональными списками кнопок и медиа.
    """
    ts = timestamp or datetime.datetime.utcnow()
    buttons_json = json.dumps(buttons, ensure_ascii=False) if buttons else ''
    media_json   = json.dumps(media,   ensure_ascii=False) if media   else ''

    cursor = await conn.cursor()
    await cursor.execute(
        """
        INSERT INTO participant_messages
          (user_tg_id, sender, text, is_answer, buttons, media, timestamp, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (user_tg_id, sender, text, int(is_answer), buttons_json, media_json, ts),
    )
    await conn.commit()
    return cursor.lastrowid

@with_connection
async def mark_message_deleted(message_id: int, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(
        "UPDATE participant_messages SET is_deleted = 1 WHERE id = ?",
        (message_id,),
    )
    await conn.commit()

@with_connection
async def get_participant_messages(
    user_tg_id: int,
    include_deleted: bool = False,
    conn=None,
) -> List[Dict[str, Any]]:
    cursor = await conn.cursor()
    sql = """
      SELECT id, sender, text, is_answer, timestamp, is_deleted
      FROM participant_messages
      WHERE user_tg_id = ?
    """
    params = [user_tg_id]
    if not include_deleted:
        sql += " AND is_deleted = 0"
    sql += " ORDER BY timestamp ASC"
    await cursor.execute(sql, params)
    rows = await cursor.fetchall()
    await conn.commit()
    # sqlite returns tuples, можно обернуть в dict
    return [
        {
            "id": r[0],
            "sender": r[1],
            "text": r[2],
            "is_answer": bool(r[3]),
            "timestamp": r[4].isoformat(),
            "is_deleted": bool(r[5]),
        }
        for r in rows
    ]


@with_connection
async def add_question(user_tg_id: int, text: str, type_: str = 'text', status: str = 'Новый', conn=None) -> int:
    cursor = await conn.cursor()
    await cursor.execute(
        "INSERT INTO questions (user_tg_id, text, type, status) VALUES (?, ?, ?, ?)",
        (user_tg_id, text, type_, status),
    )
    await conn.commit()
    return cursor.lastrowid


@with_connection
async def add_question_message(
    question_id: int,
    sender: str,
    text: str,
    is_answer: bool = False,
    media: list[dict[str, Any]] | None = None,
    conn=None,
) -> int:
    cursor = await conn.cursor()
    media_json = json.dumps(media) if media else None
    await cursor.execute(
        "INSERT INTO question_messages (question_id, sender, text, is_answer, media) VALUES (?, ?, ?, ?, ?)",
        (question_id, sender, text, int(is_answer), media_json),
    )
    await conn.commit()
    return cursor.lastrowid


@with_connection
async def is_user_blocked(user_tg_id: int, conn=None) -> bool:
    """Return True if participant is marked as blocked."""
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT blocked FROM participant_settings WHERE user_tg_id = ?",
        (user_tg_id,),
    )
    row = await cursor.fetchone()
    await conn.commit()
    return bool(row[0]) if row else False


@with_connection
async def get_questions(conn=None) -> List[Dict[str, Any]]:
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT id, user_tg_id, text, type, status, create_dt FROM questions ORDER BY create_dt DESC"
    )
    rows = await cursor.fetchall()
    await conn.commit()
    return [
        {
            "id": r[0],
            "user_tg_id": r[1],
            "text": r[2],
            "type": r[3],
            "status": r[4],
            "create_dt": r[5].isoformat() if hasattr(r[5], 'isoformat') else r[5],
        }
        for r in rows
    ]


@with_connection
async def get_question_messages(question_id: int, conn=None) -> List[Dict[str, Any]]:
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT question_id, sender, text, is_answer, timestamp FROM question_messages WHERE question_id = ? ORDER BY timestamp",
        (question_id,),
    )
    rows = await cursor.fetchall()
    await conn.commit()
    return [
        {
            "question_id": r[0],
            "sender": r[1],
            "text": r[2],
            "is_answer": bool(r[3]),
            "timestamp": r[4].isoformat() if hasattr(r[4], 'isoformat') else r[4],
        }
        for r in rows
    ]


@with_connection
async def get_active_stage(date: datetime.date | None = None, conn=None) -> dict | None:
    """Единственный "активный" этап во всей системе (глобальная эксклюзивность — только
    ОДИН этап может иметь status='active' одновременно, обеспечивается на записи в
    site_bot/main.py:save_draw()). Дата — доп. фильтр по диапазону этапа, если он задан
    (NULL-даты = без ограничения по датам)."""
    date = date or datetime.date.today()
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT * FROM prize_draw_stages WHERE status = 'active' "
        "AND (start_date IS NULL OR start_date <= ?) "
        "AND (end_date IS NULL OR end_date >= ?) "
        "ORDER BY id LIMIT 1",
        (date, date),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


@with_connection
async def get_active_draw_id(date: datetime.date | None = None, conn=None) -> int | None:
    """Id акции, содержащей единственный активный этап (для обратной совместимости мест,
    которым нужен только draw_id, не весь этап)."""
    stage = await get_active_stage(date=date, conn=conn)
    return stage["draw_id"] if stage else None


@with_connection
async def get_stage_rules(stage_id: int, only_active: bool = True, conn=None) -> list[dict]:
    """Правила проверки чеков для этапа. Пустой список = правил нет (fallback на keywords)."""
    schema = await get_table_info(conn, "prize_draw_rules")
    if not schema:
        return []
    cursor = await conn.cursor()
    query = "SELECT * FROM prize_draw_rules WHERE stage_id = ?"
    params: list = [stage_id]
    if only_active:
        query += " AND is_active = 1"
    query += " ORDER BY id"
    await cursor.execute(query, tuple(params))
    rows = await cursor.fetchall()
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@with_connection
async def get_draw_stages(draw_id: int, conn=None) -> list[dict]:
    """Этапы акции (включая stage_type), отсортированные по order_index."""
    schema = await get_table_info(conn, "prize_draw_stages")
    if not schema:
        return []
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT * FROM prize_draw_stages WHERE draw_id = ? ORDER BY order_index, id",
        (draw_id,),
    )
    rows = await cursor.fetchall()
    columns = [col[0] for col in cursor.description]
    stages = [dict(zip(columns, row)) for row in rows]
    if "stage_type" not in schema:
        for stage in stages:
            stage["stage_type"] = "standard"
    return stages


@with_connection
async def get_stage(stage_id: int, conn=None) -> dict | None:
    """Один этап по id (со всеми полями, включая stage_type/даты/статус/автовалидацию)."""
    schema = await get_table_info(conn, "prize_draw_stages")
    if not schema:
        return None
    cursor = await conn.cursor()
    await cursor.execute("SELECT * FROM prize_draw_stages WHERE id = ?", (stage_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    columns = [col[0] for col in cursor.description]
    stage = dict(zip(columns, row))
    if "stage_type" not in schema:
        stage["stage_type"] = "standard"
    return stage


@with_connection
async def get_user_rule_progress(
    user_tg_id: int, draw_id: int, rule_ids: list[int], conn=None
) -> dict[int, float]:
    """Сумма quantity по receipt_items для данных правил, только по 'Подтверждён' чекам этого
    пользователя в рамках акции (раздел 3.1/11.7 ТЗ). Правило без единой позиции — 0.0."""
    progress: dict[int, float] = {rid: 0.0 for rid in rule_ids}
    if not rule_ids:
        return progress
    placeholders = ", ".join("?" for _ in rule_ids)
    cursor = await conn.cursor()
    await cursor.execute(
        f"""
        SELECT receipt_items.matched_rule_id, SUM(receipt_items.quantity)
        FROM receipt_items
        JOIN receipts ON receipts.id = receipt_items.receipt_id
        WHERE receipts.user_tg_id = ?
          AND receipts.draw_id = ?
          AND receipt_items.matched_rule_id IN ({placeholders})
          AND receipts.status = 'Подтверждён'
        GROUP BY receipt_items.matched_rule_id
        """,
        (user_tg_id, draw_id, *rule_ids),
    )
    rows = await cursor.fetchall()
    for rule_id, total in rows:
        progress[rule_id] = float(total) if total is not None else 0.0
    return progress


@with_connection
async def is_stage_winner(stage_id: int, user_tg_id: int, conn=None) -> bool:
    """True, если пользователь уже победитель этого этапа (prize_draw_winners)."""
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT 1 FROM prize_draw_winners WHERE stage_id = ? AND user_tg_id = ? LIMIT 1",
        (stage_id, user_tg_id),
    )
    return await cursor.fetchone() is not None


@with_connection
async def add_stage_winner(
    stage_id: int, user_tg_id: int, receipt_id: int | None, winner_name: str, conn=None
) -> None:
    """Зафиксировать автоматическую победу гарантированного этапа (раздел 3.1 ТЗ)."""
    schema = await get_table_info(conn, "prize_draw_winners")
    fields = ["stage_id", "user_tg_id", "winner_name"]
    values: list = [stage_id, user_tg_id, winner_name]
    if "receipt_id" in schema:
        fields.append("receipt_id")
        values.append(receipt_id)
    placeholders = ", ".join(["?"] * len(values))
    cursor = await conn.cursor()
    await cursor.execute(
        f"INSERT INTO prize_draw_winners ({', '.join(fields)}) VALUES ({placeholders})",
        tuple(values),
    )
    await conn.commit()


@with_connection
async def add_manual_receipt_item(
    receipt_id: int, rule_id: int, quantity: float | None, conn=None
) -> None:
    """Добавить позицию чека вручную (админ), НЕ стирая уже сохранённые ФНС-позиции —
    в отличие от save_receipt_items(), которая делает DELETE перед вставкой (раздел 4.7 ТЗ)."""
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT title FROM prize_draw_rules WHERE id = ?", (rule_id,)
    )
    rule_row = await cursor.fetchone()
    raw_name = f"Ручной ввод: {rule_row[0]}" if rule_row else "Ручной ввод"
    await cursor.execute(
        "INSERT INTO receipt_items (receipt_id, raw_name, quantity, price, sum, matched_rule_id) "
        "VALUES (?, ?, ?, NULL, NULL, ?)",
        (receipt_id, raw_name, quantity, rule_id),
    )
    await conn.commit()


@with_connection
async def evaluate_guaranteed_prize_stage(
    stage: dict,
    user_tg_id: int,
    draw_id: int,
    receipt_id: int | None,
    winner_name: str,
    conn=None,
) -> dict:
    """Пересчитать прогресс пользователя по правилам гарантированного этапа и, если условия
    впервые выполнены, зафиксировать победу (add_stage_winner). Общая функция для автопайплайна
    (media_heandler.process_receipt) и ручного подтверждения администратором
    (site_bot/main.py:update_receipt) — раздел 4.6 ТЗ, «прогресс пересчитывается в обоих местах».

    Возвращает {"outcome": "already_winner" | "no_rules" | "won" | "progress",
                "rule_progress": [...]}  (rule_progress отсутствует для already_winner/no_rules).
    """
    stage_id = stage["id"]
    if await is_stage_winner(stage_id, user_tg_id, conn=conn):
        return {"outcome": "already_winner"}

    rules = await get_stage_rules(stage_id, only_active=True, conn=conn)
    if not rules:
        return {"outcome": "no_rules"}

    rule_ids = [r["id"] for r in rules]
    progress = await get_user_rule_progress(user_tg_id, draw_id, rule_ids, conn=conn)
    rule_progress = [
        {
            "id": r["id"],
            "title": r["title"],
            "min_quantity": r.get("min_quantity") or 1,
            "progress": progress.get(r["id"], 0.0),
        }
        for r in rules
    ]
    all_done = all(rp["progress"] >= rp["min_quantity"] for rp in rule_progress)
    if all_done:
        await add_stage_winner(stage_id, user_tg_id, receipt_id, winner_name, conn=conn)
        return {"outcome": "won", "rule_progress": rule_progress}
    return {"outcome": "progress", "rule_progress": rule_progress}


@with_connection
async def evaluate_standard_stage_progress(
    stage: dict, user_tg_id: int, draw_id: int, conn=None,
) -> dict:
    """Пересчитать накопленный прогресс standard-этапа (та же модель накопления, что и
    у guaranteed_prize, — см. evaluate_guaranteed_prize_stage). В отличие от неё, НИКОГДА
    не пишет в prize_draw_winners: победитель standard-этапа выбирается вручную, случайным
    розыгрышем среди тех, кто выполнил все правила (site_bot/main.py: api_determine_winners).

    Возвращает {"outcome": "no_rules" | "complete" | "progress", "rule_progress": [...],
    "entries_count": int} (rule_progress/entries_count отсутствуют для no_rules).
    entries_count — число попыток выиграть на standard-этапе, см.
    receipt_validation.compute_entries_count() (НЕ число чеков — комплект условий может
    собираться из нескольких чеков или перевыполняться одним).
    """
    rules = await get_stage_rules(stage["id"], only_active=True, conn=conn)
    if not rules:
        return {"outcome": "no_rules"}

    rule_ids = [r["id"] for r in rules]
    progress = await get_user_rule_progress(user_tg_id, draw_id, rule_ids, conn=conn)
    rule_progress = [
        {
            "id": r["id"],
            "title": r["title"],
            "min_quantity": r.get("min_quantity") or 1,
            "progress": progress.get(r["id"], 0.0),
        }
        for r in rules
    ]
    all_done = all(rp["progress"] >= rp["min_quantity"] for rp in rule_progress)
    entries_count = receipt_validation.compute_entries_count(rule_progress)
    return {
        "outcome": "complete" if all_done else "progress",
        "rule_progress": rule_progress,
        "entries_count": entries_count,
    }


@with_connection
async def get_stage_progress(stage_id: int, rules: list[dict] | None = None, conn=None) -> list[dict]:
    """Прогресс ВСЕХ пользователей, у кого есть хотя бы одна позиция чека, сматченная на
    правила этапа (для UI /prize-draws и для фильтра api_determine_winners). В отличие от
    get_user_rule_progress() — не для одного пользователя, а батчем по всем сразу.

    Возвращает [{"user_tg_id", "user_name", "rule_progress": [...], "complete": bool,
    "entry_receipt_ids": [...], "entries_count": int}, ...]. entry_receipt_ids — id
    подтверждённых чеков, засчитанных в правила этапа (используется api_determine_winners(),
    чтобы в розыгрыш не попадали чеки пользователя, никак не связанные с этим этапом, и
    чтобы выбрать чек-представитель для отображения победителя). entries_count — число
    попыток выиграть (см. receipt_validation.compute_entries_count()) — НЕ длина
    entry_receipt_ids: комплект условий может собираться из нескольких чеков или
    перевыполняться одним, поэтому число попыток и число чеков-билетов, как правило, не
    совпадают. Пустой список, если у этапа нет активных правил ИЛИ ни у кого ещё нет ни
    одной подходящей позиции — это разные случаи, вызывающий код при необходимости
    различает их отдельным вызовом get_stage_rules().
    """
    stage = await get_stage(stage_id, conn=conn)
    if not stage:
        return []
    if rules is None:
        rules = await get_stage_rules(stage_id, only_active=True, conn=conn)
    if not rules:
        return []

    rule_ids = [r["id"] for r in rules]
    draw_id = stage["draw_id"]
    placeholders = ", ".join("?" for _ in rule_ids)
    cursor = await conn.cursor()
    await cursor.execute(
        f"""
        SELECT receipts.user_tg_id, receipt_items.matched_rule_id, SUM(receipt_items.quantity)
        FROM receipt_items
        JOIN receipts ON receipts.id = receipt_items.receipt_id
        WHERE receipts.draw_id = ?
          AND receipt_items.matched_rule_id IN ({placeholders})
          AND receipts.status = 'Подтверждён'
        GROUP BY receipts.user_tg_id, receipt_items.matched_rule_id
        """,
        (draw_id, *rule_ids),
    )
    rows = await cursor.fetchall()

    progress_by_user: dict[int, dict[int, float]] = {}
    for user_tg_id, rule_id, total in rows:
        progress_by_user.setdefault(user_tg_id, {})[rule_id] = float(total) if total is not None else 0.0

    if not progress_by_user:
        return []

    user_ids = list(progress_by_user.keys())
    user_placeholders = ", ".join("?" for _ in user_ids)
    await cursor.execute(
        f"SELECT tg_id, name FROM users WHERE tg_id IN ({user_placeholders})",
        tuple(user_ids),
    )
    names = {tg_id: name for tg_id, name in await cursor.fetchall()}

    await cursor.execute(
        f"""
        SELECT DISTINCT receipts.user_tg_id, receipt_items.receipt_id
        FROM receipt_items
        JOIN receipts ON receipts.id = receipt_items.receipt_id
        WHERE receipts.draw_id = ?
          AND receipt_items.matched_rule_id IN ({placeholders})
          AND receipts.status = 'Подтверждён'
        """,
        (draw_id, *rule_ids),
    )
    entry_receipt_ids_by_user: dict[int, list[int]] = {}
    for user_tg_id, receipt_id in await cursor.fetchall():
        entry_receipt_ids_by_user.setdefault(user_tg_id, []).append(receipt_id)

    result = []
    for user_tg_id, rule_totals in progress_by_user.items():
        rule_progress = [
            {
                "id": r["id"],
                "title": r["title"],
                "min_quantity": r.get("min_quantity") or 1,
                "progress": rule_totals.get(r["id"], 0.0),
            }
            for r in rules
        ]
        complete = all(rp["progress"] >= rp["min_quantity"] for rp in rule_progress)
        entry_receipt_ids = entry_receipt_ids_by_user.get(user_tg_id, [])
        result.append({
            "user_tg_id": user_tg_id,
            "user_name": names.get(user_tg_id),
            "rule_progress": rule_progress,
            "complete": complete,
            "entry_receipt_ids": entry_receipt_ids,
            "entries_count": receipt_validation.compute_entries_count(rule_progress),
        })
    return result


@with_connection
async def save_receipt_items(receipt_id: int, items: list[dict], conn=None) -> None:
    """Заменить сохранённые позиции чека новыми (безопасно при повторной обработке)."""
    schema = await get_table_info(conn, "receipt_items")
    if not schema:
        return
    cursor = await conn.cursor()
    await cursor.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
    for item in items:
        await cursor.execute(
            "INSERT INTO receipt_items (receipt_id, raw_name, quantity, price, sum, matched_rule_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                receipt_id,
                item.get("raw_name"),
                item.get("quantity"),
                item.get("price"),
                item.get("sum"),
                item.get("matched_rule_id"),
            ),
        )
    await conn.commit()


@with_connection
async def get_receipt_items(receipt_id: int, conn=None) -> list[dict]:
    """Позиции чека из ФНС, сохранённые ранее (пустой список, если таблицы нет)."""
    schema = await get_table_info(conn, "receipt_items")
    if not schema:
        return []
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY id", (receipt_id,)
    )
    rows = await cursor.fetchall()
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


@with_connection
async def add_receipt(
    file_path: str,
    user_tg_id: int,
    status: str = "не подтвержден",
    number: str | None = None,
    date: str | None = None,
    amount: float | None = None,
    message_id: int | None = None,
    qr: str | None = None,
    draw_id: int | None = None,
    stage_id: int | None = None,
    conn=None,
) -> int:
    """Сохранить чек пользователя."""
    cursor = await conn.cursor()
    await ensure_receipt_comment_column(conn=conn)
    schema = await get_table_info(conn, "receipts")
    fields = ["number", "date", "amount", "user_tg_id"]
    values = [number, date, amount, user_tg_id]
    if "draw_id" in schema:
        fields.append("draw_id")
        values.append(draw_id)
    if "stage_id" in schema:
        fields.append("stage_id")
        values.append(stage_id)
    if "message_id" in schema:
        fields.append("message_id")
        values.append(message_id)
    if "qr" in schema and qr is not None:
        fields.append("qr")
        values.append(qr)
    fields.extend(["file_path", "status"])
    values.extend([file_path, status])
    placeholders = ", ".join(["?"] * len(values))
    await cursor.execute(
        f"INSERT INTO receipts ({', '.join(fields)}) VALUES ({placeholders})",
        tuple(values),
    )
    await conn.commit()
    return cursor.lastrowid


@with_connection
async def enqueue_receipt_ocr(receipt_id: int, conn=None) -> None:
    """Add a receipt to the OCR processing queue."""
    await conn.execute(
        """
        INSERT INTO receipt_ocr_queue (receipt_id, status, attempts, last_error, locked_at, updated_at, available_at)
        VALUES (?, 'pending', 0, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(receipt_id) DO UPDATE SET
            status = 'pending',
            attempts = 0,
            last_error = NULL,
            locked_at = NULL,
            updated_at = CURRENT_TIMESTAMP,
            available_at = CURRENT_TIMESTAMP
        """,
        (receipt_id,),
    )
    await conn.commit()


@with_connection
async def acquire_next_receipt_for_ocr(
    lock_timeout_seconds: int = 300,
    conn=None,
) -> Tuple[int, int, int] | None:
    """Reserve the next available OCR job and return (queue_id, receipt_id, attempts)."""
    await conn.execute("BEGIN IMMEDIATE")
    cursor = await conn.execute(
        """
        SELECT id, receipt_id, attempts
        FROM receipt_ocr_queue
        WHERE (
                status = 'pending'
                AND (available_at IS NULL OR available_at <= CURRENT_TIMESTAMP)
            )
            OR (
                status = 'processing'
                AND (
                    locked_at IS NULL
                    OR locked_at <= datetime('now', ?)
                )
            )
        ORDER BY
            CASE WHEN status = 'processing' THEN 0 ELSE 1 END,
            updated_at ASC,
            id ASC
        LIMIT 1
        """,
        (f"-{lock_timeout_seconds} seconds",),
    )
    row = await cursor.fetchone()
    if row is None:
        await conn.rollback()
        return None

    queue_id, receipt_id, attempts = row
    await conn.execute(
        """
        UPDATE receipt_ocr_queue
        SET status = 'processing',
            attempts = ?,
            locked_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (attempts + 1, queue_id),
    )
    await conn.commit()
    return queue_id, receipt_id, attempts + 1


@with_connection
async def mark_receipt_queue_complete(queue_id: int, conn=None) -> None:
    """Mark an OCR queue job as completed."""
    await conn.execute(
        """
        UPDATE receipt_ocr_queue
        SET status = 'done',
            last_error = NULL,
            locked_at = NULL,
            updated_at = CURRENT_TIMESTAMP,
            available_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (queue_id,),
    )
    await conn.commit()


@with_connection
async def mark_receipt_queue_failed(
    queue_id: int,
    error_message: str,
    retry_delay_seconds: int = 60,
    conn=None,
) -> None:
    """Return a queue job back to pending state with error description."""
    await conn.execute(
        """
        UPDATE receipt_ocr_queue
        SET status = 'pending',
            last_error = ?,
            locked_at = NULL,
            updated_at = CURRENT_TIMESTAMP,
            available_at = datetime('now', ?)
        WHERE id = ?
        """,
        (error_message[:512], f"+{retry_delay_seconds} seconds", queue_id),
    )
    await conn.commit()


@with_connection
async def update_receipt_status(
    receipt_id: int,
    status: str,
    comment: Optional[str] = None,
    conn=None,
) -> str | None:
    """Update status (and optionally comment) for a receipt. Returns previous status."""
    await ensure_receipt_comment_column(conn=conn)
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT status FROM receipts WHERE id = ?",
        (receipt_id,)
    )
    row = await cursor.fetchone()
    old_status = row[0] if row else None
    if comment is None:
        await cursor.execute(
            "UPDATE receipts SET status = ? WHERE id = ?",
            (status, receipt_id),
        )
    else:
        await cursor.execute(
            "UPDATE receipts SET status = ?, comment = ? WHERE id = ?",
            (status, comment, receipt_id),
        )
    await conn.commit()
    return old_status


def _receipt_select_columns(existing_columns: Iterable[str]) -> list[str]:
    existing = {name.lower(): name for name in existing_columns}
    select_parts: list[str] = []
    for column in RECEIPT_COLUMN_NAMES:
        lower = column.lower()
        if column == "id":
            if lower in existing:
                select_parts.append(f"COALESCE(NULLIF({existing[lower]}, ''), rowid)")
            else:
                select_parts.append("rowid")
        elif lower in existing:
            select_parts.append(existing[lower])
        else:
            select_parts.append("NULL")
    return select_parts


def _build_receipts_table_sql(table_name: str) -> str:
    columns_definition = ", ".join(
        f"{name} {definition}" for name, definition in RECEIPT_COLUMNS_ORDER
    )
    return f"CREATE TABLE {table_name} ({columns_definition})"


def _normalise_receipt_id_value(raw_id, used_ids: set[int]) -> Optional[int]:
    """Return a positive, unused integer id or None to autogenerate."""
    normalized_id: Optional[int] = None
    if isinstance(raw_id, int) and not isinstance(raw_id, bool):
        normalized_id = raw_id if raw_id > 0 else None
    elif isinstance(raw_id, (str, bytes)):
        text = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        text = text.strip()
        if text:
            try:
                candidate = int(text)
            except ValueError:
                candidate = None
            else:
                normalized_id = candidate if candidate > 0 else None
    else:
        try:
            candidate = int(raw_id)
        except (TypeError, ValueError):
            candidate = None
        else:
            normalized_id = candidate if candidate > 0 else None

    if normalized_id is None or normalized_id in used_ids:
        return None
    used_ids.add(normalized_id)
    return normalized_id


def _prepare_receipt_rows(rows: Iterable[Iterable]) -> list[tuple]:
    used_ids: set[int] = set()
    sanitized_rows: list[tuple] = []
    for row in rows:
        mutable_row = list(row)
        mutable_row[0] = _normalise_receipt_id_value(mutable_row[0], used_ids)
        sanitized_rows.append(tuple(mutable_row))
    return sanitized_rows


def _rebuild_receipts_table_sync(
    conn: sqlite3.Connection, existing_columns: Iterable[str]
) -> None:
    conn.execute("DROP TABLE IF EXISTS receipts_new")
    conn.execute(_build_receipts_table_sql("receipts_new"))
    select_parts = _receipt_select_columns(existing_columns)
    cursor = conn.execute(
        f"SELECT {', '.join(select_parts)} FROM receipts"
    )
    rows = cursor.fetchall()
    cursor.close()

    sanitized_rows = _prepare_receipt_rows(rows)

    if sanitized_rows:
        placeholders = ", ".join(["?"] * len(RECEIPT_COLUMN_NAMES))
        insert_sql = (
            f"INSERT INTO receipts_new ({', '.join(RECEIPT_COLUMN_NAMES)}) "
            f"VALUES ({placeholders})"
        )
        conn.executemany(insert_sql, sanitized_rows)

    conn.execute("DROP TABLE receipts")
    conn.execute("ALTER TABLE receipts_new RENAME TO receipts")
    conn.commit()


async def _rebuild_receipts_table_async(conn, existing_columns: Iterable[str]) -> None:
    await conn.execute("DROP TABLE IF EXISTS receipts_new")
    await conn.execute(_build_receipts_table_sql("receipts_new"))
    select_parts = _receipt_select_columns(existing_columns)
    cursor = await conn.execute(
        f"SELECT {', '.join(select_parts)} FROM receipts"
    )
    rows = await cursor.fetchall()
    await cursor.close()

    sanitized_rows = _prepare_receipt_rows(rows)

    if sanitized_rows:
        placeholders = ", ".join(["?"] * len(RECEIPT_COLUMN_NAMES))
        insert_sql = (
            f"INSERT INTO receipts_new ({', '.join(RECEIPT_COLUMN_NAMES)}) "
            f"VALUES ({placeholders})"
        )
        await conn.executemany(insert_sql, sanitized_rows)

    await conn.execute("DROP TABLE receipts")
    await conn.execute("ALTER TABLE receipts_new RENAME TO receipts")
    await conn.commit()


def ensure_receipt_comment_column_sync(db_path: Optional[str] = None) -> bool:
    """Ensure the receipts table contains the comment column and a proper PK."""
    path = db_path or db_name
    if not path:
        return False
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='receipts'"
            )
            if cursor.fetchone() is None:
                return False

            columns_info = conn.execute("PRAGMA table_info(receipts)").fetchall()
            column_names = [row[1] for row in columns_info]
            has_comment = "comment" in column_names
            pk_columns = [row for row in columns_info if row[5]]
            needs_rebuild = len(pk_columns) != 1 or pk_columns[0][1] != "id"

            if not has_comment:
                try:
                    conn.execute("ALTER TABLE receipts ADD COLUMN comment TEXT")
                    conn.commit()
                    column_names.append("comment")
                    has_comment = True
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" in str(exc).lower():
                        has_comment = True
                    else:
                        logger.error(
                            "Failed to add comment column to receipts: %s", exc
                        )

            if needs_rebuild:
                try:
                    _rebuild_receipts_table_sync(conn, column_names)
                except Exception:
                    logger.exception(
                        "Failed to rebuild receipts table to restore primary key"
                    )
                    return False

            return has_comment or needs_rebuild
    except sqlite3.OperationalError as exc:
        if "duplicate column name" in str(exc).lower():
            return True
        logger.error("Failed to ensure receipts schema: %s", exc)
    except Exception:
        logger.exception("Unexpected error while ensuring receipts schema")
    return False


@with_connection
async def ensure_receipt_comment_column(conn=None) -> bool:
    """Ensure the receipts table contains a comment column."""
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='receipts'"
    )
    table_exists = await cursor.fetchone()
    await cursor.close()
    if not table_exists:
        return False
    cursor = await conn.execute("PRAGMA table_info(receipts)")
    columns_info = await cursor.fetchall()
    await cursor.close()

    column_names = [row[1] for row in columns_info]
    has_comment = "comment" in column_names
    pk_columns = [row for row in columns_info if row[5]]
    needs_rebuild = len(pk_columns) != 1 or pk_columns[0][1] != "id"

    if not has_comment:
        try:
            await conn.execute("ALTER TABLE receipts ADD COLUMN comment TEXT")
            await conn.commit()
            column_names.append("comment")
            has_comment = True
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                has_comment = True
            else:
                logger.error(
                    "Failed to add comment column to receipts asynchronously: %s",
                    exc,
                )

    if needs_rebuild:
        try:
            await _rebuild_receipts_table_async(conn, column_names)
        except Exception:
            logger.exception(
                "Failed to rebuild receipts table asynchronously to restore primary key"
            )
            return False

    return has_comment or needs_rebuild


@with_connection
async def update_receipt_comment(receipt_id: int, comment: Optional[str], conn=None) -> None:
    """Update the comment column for a receipt if the schema supports it."""
    if not await ensure_receipt_comment_column(conn=conn):
        return
    await conn.execute(
        "UPDATE receipts SET comment = ? WHERE id = ?",
        (comment, receipt_id),
    )
    await conn.commit()


@with_connection
async def update_receipt_qr(receipt_id: int, qr: str, conn=None) -> None:
    """Set QR code string for a receipt."""
    cursor = await conn.cursor()
    await cursor.execute(
        "UPDATE receipts SET qr = ? WHERE id = ?",
        (qr, receipt_id),
    )
    await conn.commit()


@with_connection
async def find_receipt_by_qr(qr: str, conn=None) -> int | None:
    """Return receipt id with given QR or None."""
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT id FROM receipts WHERE qr = ?",
        (qr,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


@with_connection
async def get_receipt(receipt_id: int, conn=None) -> dict | None:
    """Return a receipt row as dict or None."""
    cursor = await conn.cursor()
    await cursor.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


@with_connection
async def has_receipt_draw_id(conn=None) -> bool:
    """Return True if the receipts table has a draw_id column."""
    schema = await get_table_info(conn, "receipts")
    return "draw_id" in schema


@with_connection
async def get_user_receipts(
    user_tg_id: int, limit: int | None = 5, draw_id: int | None = None, conn=None
) -> List[Dict[str, Any]]:
    """Return user's receipts sorted by newest."""
    cursor = await conn.cursor()
    query = (
        "SELECT id, file_path, status, create_dt FROM receipts "
        "WHERE user_tg_id = ?"
    )
    params: list[Any] = [user_tg_id]
    if draw_id is not None and await has_receipt_draw_id(conn=conn):
        query += " AND draw_id = ?"
        params.append(draw_id)
    query += " ORDER BY create_dt DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    await cursor.execute(query, tuple(params))
    rows = await cursor.fetchall()
    await conn.commit()
    return [
        {
            "id": r[0],
            "file_path": r[1],
            "status": r[2],
            "create_dt": r[3].isoformat() if hasattr(r[3], "isoformat") else r[3],
        }
        for r in rows
    ]


@with_connection
async def delete_receipt(receipt_id: int, conn=None) -> None:
    cursor = await conn.cursor()
    await cursor.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
    await conn.commit()

@with_connection
async def delete_all_user_data(
    user_tg_id: int,
    *,
    keep_admin: bool = False,
    conn=None,
):
    cursor = await conn.cursor()

    tables = [
        ("users", "tg_id"),
        ("user_settings", "tg_id"),
        ("user_extended", "tg_id"),
        ("user_params", "user_tg_id"),
        ("user_rule", "user_tg_id"),
        ("history_user", "user_tg_id"),
        ("last_image", "user_tg_id"),
        ("visite_log", "user_tg_id"),
        ("params", "user_tg_id"),
        ("admins", "user_tg_id"),
        ("wallet_log", "user_tg_id"),
        ("cancel_order", "user_tg_id"),
        ("params_site", "user_tg_id"),
        ("participant_settings", "user_tg_id"),
        ("participant_messages", "user_tg_id"),
        ("prize_draw_winners", "user_tg_id"),
        ("receipts", "user_tg_id"),
        ("notifications", "user_tg_id"),
    ]

    for table, column in tables:
        if keep_admin and table == "admins":
            continue
        await cursor.execute(
            f"DELETE FROM {table} WHERE {column} = ?", (user_tg_id,)
        )

    await cursor.execute("SELECT id FROM questions WHERE user_tg_id = ?", (user_tg_id,))
    q_ids = [row[0] for row in await cursor.fetchall()]
    if q_ids:
        placeholders = ",".join(["?"] * len(q_ids))
        await cursor.execute(
            f"DELETE FROM question_messages WHERE question_id IN ({placeholders})",
            tuple(q_ids),
        )
        await cursor.execute(
            f"DELETE FROM questions WHERE id IN ({placeholders})", tuple(q_ids)
        )

    await cursor.execute("SELECT id FROM images WHERE user_tg_id = ?", (user_tg_id,))
    img_ids = [row[0] for row in await cursor.fetchall()]
    if img_ids:
        placeholders = ",".join(["?"] * len(img_ids))
        await cursor.execute(
            f"DELETE FROM deleted_images WHERE image_id IN ({placeholders})",
            tuple(img_ids),
        )
    await cursor.execute("DELETE FROM images WHERE user_tg_id = ?", (user_tg_id,))

    await cursor.execute(
        "SELECT no FROM sales_header WHERE client_id = ?", (user_tg_id,)
    )
    sales = [row[0] for row in await cursor.fetchall()]
    for sale_no in sales:
        await cursor.execute(
            "DELETE FROM sales_line WHERE sales_no = ?", (sale_no,)
        )
        await cursor.execute(
            "DELETE FROM additional_field WHERE sales_no = ?", (sale_no,)
        )
    await cursor.execute(
        "DELETE FROM sales_header WHERE client_id = ?", (user_tg_id,)
    )
    await conn.commit()
