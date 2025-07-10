import aiosqlite
import asyncio
import os
import sys
import datetime
import sqlite3
import json


exetp_path = '/home/server/tg_build_bot/information_telegram_bot/pyment_bot_dir/'

db_name = exetp_path + "pytment_bot_db.sqlite"


''' Созадём таблицы '''
# ==================================================================
async def create_table(conn, create_execute_script):
    cursor = await conn.cursor()
    await cursor.execute('CREATE TABLE IF NOT EXISTS ' + create_execute_script)
    await conn.commit()


async def create_db():
    #current_directory = os.path.dirname(os.path.abspath(__file__))
    #table_shem_path = os.path.join(current_directory, 'table_shem_bot_pay.json')
    table_shem_file_name = exetp_path + 'table_shem_bot_pay.json'
    #print(table_shem_path)
    #table_shem_path = '/Users/romanzhdanov/My_project/information_telegram_bot/table_shem.json'

    with open(table_shem_file_name, 'rb') as table_shem_file:
        # Загружаем переменные из файла
        table_shem = json.load(table_shem_file)

    async with aiosqlite.connect(db_name) as conn:
        # Создаем таблицу
        for keys in table_shem.keys():
            await create_table(conn, table_shem.get(keys))
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


@with_connection_def
def create_payment_invite_key(user_data: str, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM payment_invite WHERE create_dt < datetime('now', '-1 hour');")
    cursor.execute(f"INSERT INTO payment_invite (data_json) VALUES ('{user_data}');")
    new_record_id = cursor.lastrowid
    cursor.execute("SELECT random_key FROM payment_invite WHERE ROWID=?", (new_record_id,))
    autoincrement_key_value = cursor.fetchone()
    conn.commit()

    return autoincrement_key_value[0]


@with_connection
async def get_pyment_data(key:str, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"DELETE FROM payment_invite WHERE create_dt < datetime('now', '-1 hour');")
    await cursor.execute(f"SELECT data_json FROM payment_invite WHERE random_key = '{key}';")
    result = await cursor.fetchone()
    await cursor.execute(f"DELETE FROM payment_invite WHERE random_key = '{key}';")
    await conn.commit()

    if not result:
        return result

    return result[0]


@with_connection
async def create_payment_need_pay(user_data: str, hash: str, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"INSERT INTO payment_need_pay (data_json, hash) VALUES ('{user_data}', '{hash}');")
    new_record_id = cursor.lastrowid
    await cursor.execute("SELECT id FROM payment_need_pay WHERE ROWID=?", (new_record_id,))
    autoincrement_key_value = await cursor.fetchone()
    await conn.commit()

    return autoincrement_key_value[0]


@with_connection
async def get_payment_need_pay(key:str, conn=None):
    cursor = await conn.cursor()
    await cursor.execute(f"SELECT * FROM payment_need_pay WHERE id = '{key}';")
    result = await cursor.fetchone()

    if not result:
        return result

    return result


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


def get_next_month_date(date_old):
    date_new = date_old

    if date_new.day > 28:
        date_new = date_new.replace(day=1, month=date_new.month + 1) 

    date_new = date_new.replace(month=date_new.month + 1) 

    return date_new


def payment_bot(deduction_procent: float, user_tg_id: int=0, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = cursor.fetchone()
    result = dict(zip(columns, row))

    cursor.execute(f"""INSERT INTO wallet_log (user_tg_id, type, code, description, balance, total_spent_month, total_spent, next_write_off_date) 
                         VALUES ('{user_tg_id}', 
                            'PYMENT_BOT', 
                            '', 
                            'Ежемесячная оплата бота', 
                            '{result['balance'] - deduction_procent}', 
                            '0',
                            '{result['total_spent']}',
                            '{get_next_month_date(datetime.date.today())}');
                        """)
    conn.commit()

    cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = cursor.fetchone()
    result = dict(zip(columns, row))
    return result

if __name__ == "__main__":
    # Запускаем асинхронный код
    #asyncio.run(main())
    asyncio.run(create_db())