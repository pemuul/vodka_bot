import aiosqlite
import asyncio
import os
import datetime
import sqlite3
import json

from keys import DB_NAME
from typing import Dict, Any, Optional, List


global_objects = None
db_name = None

def init_object(global_objects_inp):
    global global_objects
    global db_name

    global_objects = global_objects_inp

    #print('dirname -> ', global_objects.settings_bot['run_directory'])
    db_name = f"{global_objects.settings_bot['run_directory']}/{DB_NAME}"


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
    # Получаем текущие данные из таблицы
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM {table_name}")
    data = await cursor.fetchall()

    # Создаем временную таблицу с новой схемой
    columns_definition = ', '.join([f"{col} {col_type}" for col, col_type in new_schema.items()])
    await cursor.execute(f"CREATE TABLE {table_name}_new ({columns_definition})")
    await conn.commit()

    # Копируем данные в новую таблицу, соответствующие новым столбцам
    new_columns = ', '.join(new_schema.keys())
    old_columns = ', '.join([col for col in new_schema.keys() if col in existing_schema.keys()])
    await cursor.executemany(f"INSERT INTO {table_name}_new ({new_columns}) SELECT {old_columns} FROM {table_name}", data)
    await conn.commit()

    # Удаляем старую таблицу и переименовываем новую
    await cursor.execute(f"DROP TABLE {table_name}")
    await cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")
    await conn.commit()

async def create_or_update_tables(conn, schema_dict):
    for table_name, create_execute_script in schema_dict.items():
        table_schema_raw = create_execute_script.split('(', 1)[1].rstrip(')')
        columns = table_schema_raw.split(', ')
        new_schema = {col.split()[0]: ''.join(col.split()[1]) for col in columns if not col[:6] in ['UNIQUE', 'PRIMAR']}

        # Проверяем, существует ли таблица
        cursor = await conn.cursor()
        await cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        table_exists = await cursor.fetchone()

        if table_exists:
            # Обновляем таблицу, если она существует
            await update_table(conn, table_name, new_schema)
        else:
            # Создаем таблицу, если её нет
            await create_table(conn, create_execute_script)


async def create_db():
    current_directory = os.path.dirname(os.path.abspath(__file__))
    table_shem_path = os.path.join(current_directory, 'table_shem.json')
    #print(table_shem_path)
    #table_shem_path = '/Users/romanzhdanov/My_project/information_telegram_bot/table_shem.json'

    with open(table_shem_path, 'rb') as table_shem_file:
        # Загружаем переменные из файла
        table_shem = json.load(table_shem_file)

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
        current_directory = os.path.dirname(os.path.abspath(__file__))
        table_shem_path = os.path.join(current_directory, 'table_shem.json')

        with open(table_shem_path, 'rb') as table_shem_file:
            # Загружаем переменные из файла
            table_shem = json.load(table_shem_file)
        
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
async def add_question_message(question_id: int, sender: str, text: str, is_answer: bool = False, conn=None) -> int:
    cursor = await conn.cursor()
    await cursor.execute(
        "INSERT INTO question_messages (question_id, sender, text, is_answer) VALUES (?, ?, ?, ?)",
        (question_id, sender, text, int(is_answer)),
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
async def get_active_draw_id(date: datetime.date | None = None, conn=None) -> int | None:
    """Return id of active prize draw for given date, if any."""
    date = date or datetime.date.today()
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT id FROM prize_draws WHERE status = 'active' AND start_date <= ? AND end_date >= ? ORDER BY id LIMIT 1",
        (date, date),
    )
    row = await cursor.fetchone()
    await conn.commit()
    return row[0] if row else None

@with_connection
async def add_receipt(
    file_path: str,
    user_tg_id: int,
    status: str = "не подтвержден",
    number: str | None = None,
    date: str | None = None,
    amount: float | None = None,
    message_id: int | None = None,
    draw_id: int | None = None,
    conn=None,
) -> int:
    """Сохранить чек пользователя."""
    cursor = await conn.cursor()
    schema = await get_table_info(conn, "receipts")
    fields = ["number", "date", "amount", "user_tg_id"]
    values = [number, date, amount, user_tg_id]
    if "draw_id" in schema:
        fields.append("draw_id")
        values.append(draw_id)
    if "message_id" in schema:
        fields.append("message_id")
        values.append(message_id)
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
async def update_receipt_status(receipt_id: int, status: str, conn=None) -> str | None:
    """Update status field for a receipt. Returns previous status."""
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT status FROM receipts WHERE id = ?",
        (receipt_id,)
    )
    row = await cursor.fetchone()
    old_status = row[0] if row else None
    await cursor.execute(
        "UPDATE receipts SET status = ? WHERE id = ?",
        (status, receipt_id),
    )
    await conn.commit()
    return old_status


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
