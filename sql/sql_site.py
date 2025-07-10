from sql_mgt import with_connection, with_connection_def
import random
import string
import sqlite3


''' получение и добавление параметров '''
# ==================================================================
def set_param(user_tg_id, param_name, param_value, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"INSERT OR IGNORE INTO params_site (user_tg_id, param_name, value) \
                            VALUES ({user_tg_id}, '{param_name}', '{param_value}');")
    cursor.execute(f"UPDATE params_site \
                            SET value = '{param_value}' \
                            WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}';")
    conn.commit()


def get_param(user_tg_id, param_name, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT value FROM params_site WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}'")
    result = cursor.fetchone()

    if not result: 
        return ''
    
    return_str = result[0]
    if len(return_str) > 0:
        if return_str[0] == ',':
            return_str = return_str[1:]
    return return_str


def get_user_id_by_value(param_name, param_value, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT user_tg_id FROM params_site WHERE value = '{param_value}' AND param_name = '{param_name}'")
    result = cursor.fetchone()

    if not result: 
        return ''
    
    return_id = result[0]
    return return_id


async def generate_random_key(length:int):
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) for _ in range(length))


@with_connection
async def set_param_unique_random_value(user_tg_id, param_name, conn=None):
    cursor = await conn.cursor()
    result = True
    while result:
        random_key = await generate_random_key(10)
        await cursor.execute(f"SELECT 1 FROM params_site WHERE param_name = '{random_key}'")
        result = await cursor.fetchone()

    await cursor.execute(f"INSERT OR IGNORE INTO params_site (user_tg_id, param_name, value) \
                            VALUES ({user_tg_id}, '{param_name}', '{random_key}');")
    await cursor.execute(f"UPDATE params_site \
                            SET value = '{random_key}' \
                            WHERE user_tg_id = {user_tg_id} AND param_name = '{param_name}';")
    await conn.commit()

    return random_key

# << ============= товары и заказы ===================
def get_items(conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM item WHERE activ = 'on' AND quantity > 0 ORDER BY display_priority DESC, create_dt ASC")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_all_items(conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM item ORDER BY display_priority DESC, create_dt ASC")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_item_by_id(item_id, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM item WHERE id='{item_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


def get_last_item(conn=None):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM item ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде словаря
    row = cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


def insert_item(data, conn=None):
    cursor = conn.cursor()

    # Формирование запроса на обновление записи
    values = ', '.join(['?'] * 9)
    query = f"INSERT INTO item (name, description, price, quantity, media_list, discount, requires_confirm_menager, activ, display_priority) VALUES ({values})"

    # Выполнение запроса
    cursor.execute(query, (data['product_name'], data['product_description'], data['product_price'], data['quantity'], data['media_list'], data['discount'], data['product_requires_manager'], data['product_activ'], data['display_priority']))
    conn.commit()


def update_item(data, conn=None):
    cursor = conn.cursor()
    set_clauses, params = [], []

    fields = {
        'product_name': 'name', 
        'product_description': 'description', 
        'product_price': 'price', 
        'quantity': 'quantity', 
        'media_list': 'media_list', 
        'discount': 'discount', 
        'product_requires_manager': 'requires_confirm_menager', 
        'product_activ': 'activ',
        'display_priority': 'display_priority'
    }

    for key, field in fields.items():
        if key in data and (key != 'media_list' or data[key] is not None):
            set_clauses.append(f"{field} = ?")
            params.append(data[key])

    query = f"UPDATE item SET {', '.join(set_clauses)} WHERE id = ?"
    params.append(data['product_id'])
    print(query, params)

    cursor.execute(query, params)
    conn.commit()


def delete_item(item_id:int, conn=None):
    cursor = conn.cursor()

    # Формирование запроса на обновление записи 
    query = f'''DELETE FROM item WHERE id = '{item_id}' '''

    # Выполнение запроса 
    cursor.execute(query)

    conn.commit()


def get_items_by_id(items_id:list, conn=None):
    items_id_list = [f"'{item_id}'" for item_id in items_id]
    items_id_text = ", ".join(items_id_list)

    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM item WHERE id IN ({items_id_text})")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = {}
    for row in cursor.fetchall():
        item_dict = dict(zip(columns, row))
        results[item_dict.get('id')] = item_dict

    return results


def subtract_amount_item(item_id, amount:int, conn=None):
    # вычитаем из товара число
    cursor = conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE item SET quantity = quantity - {amount} WHERE id = '{item_id}'"

    # Выполнение запроса
    cursor.execute(query)
    conn.commit()


def get_user_orders(user_id, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM sales_header WHERE client_id = '{user_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_orders(conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM sales_header")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_order(order_no, conn):
    print('conn', conn)
    cursor = conn.cursor()
    query = f"SELECT * FROM sales_header WHERE no = '{order_no}'"
    cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


def update_is_paid_for(order_no, is_paid_for, conn=None):
    cursor = conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE sales_header SET is_paid_for = ? WHERE no = '{order_no}'"

    # Выполнение запроса
    cursor.execute(query, (int(is_paid_for), ))
    conn.commit()


def get_orders_lines(orders:list, conn=None):
    if len(orders) == 0:
        return None

    order_no_list = [f"'{order.get('no')}'" for order in orders]
    order_no_text = ", ".join(order_no_list)
    
    cursor = conn.cursor()
    query = f"SELECT * FROM sales_line WHERE sales_no IN ({order_no_text})"
    print(query)
    cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_line(line_id:int, conn=None):
    cursor = conn.cursor()
    query = f"SELECT * FROM sales_line WHERE id = '{line_id}'"
    cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


def add_line(sales_no:str, item:dict, conn:None = None):
    cursor = conn.cursor()

    values = ', '.join(['?'] * 7)
    query = f'''INSERT INTO sales_line (sales_no, item_id, name, description, price, quantity, reserv) 
        VALUES ({values})'''

    item_data = {
        'sales_no': sales_no,
        'item_id': item['id'],
        'name': item['name'],
        'description': item['description'],
        'price': round(item['price'] - (item['price'] * item['discount'] / 100), 2),
        'quantity': item['quantity'],
        'reserv': item['reserv'],
    }

    cursor.execute(query, tuple(item_data.values()))

    conn.commit()


def edit_line(line:dict, conn:None = None):
    cursor = conn.cursor()

    query = f'''UPDATE sales_line SET 
        name = '{line['name']}',
        description = '{line['description']}', 
        price = '{line['price']}',
        quantity = '{line['quantity']}',
        reserv = '{line['reserv']}'
        
        WHERE id = '{line['id']}' '''

    cursor.execute(query)

    conn.commit()


def delete_line(line_id, conn:None = None):
    cursor = conn.cursor()

    query = f'''DELETE FROM sales_line WHERE id = '{line_id}' '''

    cursor.execute(query)

    conn.commit()


def update_order_status(order_no:str, status:str, conn=None):
    cursor = conn.cursor()

    # Формирование запроса на обновление записи
    query = f"UPDATE sales_header SET status = ? WHERE no = '{order_no}'"

    # Выполнение запроса
    cursor.execute(query, (status,))
    conn.commit()


def create_order(user_id, items_inp:list, conn=None):
    cursor = conn.cursor()

    cursor.execute('SELECT no FROM sales_header ORDER BY no DESC LIMIT 1;')
    last_line = cursor.fetchone()
    last_serial_number = last_line[0] if last_line else None

    new_serial_number = generate_next_serial(last_serial_number)

    cursor.execute(f"INSERT INTO sales_header (no, client_id, status) VALUES ('{new_serial_number}', '{user_id}', 'NEW')")
    conn.commit()

    values = ', '.join(['?'] * 7)
    query = f'''INSERT INTO sales_line (sales_no, item_id, name, description, price, quantity, reserv) 
        VALUES ({values})'''

    items = []
    for item_id, item in enumerate(items_inp):
        items.append({
            'sales_no': new_serial_number,
            'item_id': item['id'],
            'name': item['name'],
            'description': item['description'],
            'price': item['price'],
            'quantity': item['quantity'],
            'reserv': item['quantity']
        })
    
    # Вставляем данные из списка
    for data in items:
        cursor.execute(query, tuple(data.values()))
        
    conn.commit()

    cursor.execute(f"SELECT * FROM sales_header ORDER BY no DESC LIMIT 1;")
    columns = [column[0] for column in cursor.description]

    # Получение результата в виде словаря
    row = cursor.fetchone()
    result = dict(zip(columns, row)) if row else None

    return result


def append_additional_fields(sales_no:str, additional_fields:dict, conn:None = None):
    cursor = conn.cursor()

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
        cursor.execute(query, tuple(data.values()))

    conn.commit()


def get_additional_fields(orders:list, conn=None):
    if len(orders) == 0:
        return None

    order_no_list = [f"'{order.get('no')}'" for order in orders]
    order_no_text = ", ".join(order_no_list)
    
    cursor = conn.cursor()
    query = f"SELECT * FROM additional_field WHERE sales_no IN ({order_no_text})"
    print(query)
    cursor.execute(query)
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def generate_next_serial(last_serial_number):
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    # Если нет последнего номера, начинаем с A0000
    if last_serial_number is None:
        return 'AAA000'

    # Разбиваем номер на буквы и цифры
    letter_part = last_serial_number[:-(len(last_serial_number) - 3)]
    digit_part = last_serial_number[-3:]

    # Увеличиваем номер
    if digit_part != '999':
        new_digit_part = str(int(digit_part) + 1).zfill(3)
        return letter_part + new_digit_part
    else:
        new_letter_part = ''
        carry = True
        for letter in reversed(letter_part):
            if carry:
                if letter == 'Z':
                    new_letter_part = 'A' + new_letter_part
                else:
                    new_letter_part = alphabet[alphabet.index(letter) + 1] + new_letter_part
                    carry = False
            else:
                new_letter_part = letter + new_letter_part
        if carry:
            new_letter_part = 'A' + new_letter_part 
        return new_letter_part + '000'

# >> ============= товары и заказы ===================
    
# << ============= настройка ===================
def get_admin(user_id, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM admins WHERE user_tg_id = '{user_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    admin = cursor.fetchone()
    result = dict(zip(columns, admin)) if admin else None

    return result


def get_admins(conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM admins")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_admin_rules(user_id, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM user_rule WHERE user_tg_id = '{user_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    results = []
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))

    return results


def get_user(user_id, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM users WHERE tg_id = '{user_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    user = cursor.fetchone()
    result = dict(zip(columns, user)) if user else None

    return result


def get_user_extended(user_id, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT tg_id, username FROM user_extended WHERE tg_id = '{user_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    user = cursor.fetchone()
    result = dict(zip(columns, user)) if user else None

    return result


def update_admin_rule(user_id, rule, is_add_rule, conn=None):
    rules_line = get_admin_rules(user_id, conn)
    rules = [rule_line.get('rule') for rule_line in rules_line]

    cursor = conn.cursor()
    if is_add_rule:
        # Добавляем роль
        if rule in rules:
            return True
        
        #cursor = conn.cursor()
        cursor.execute(f'''INSERT INTO user_rule (user_tg_id, rule) 
            VALUES ('{user_id}', '{rule}')''')
    else:
        cursor.execute(f'''DELETE FROM user_rule WHERE user_tg_id = '{user_id}' AND  rule='{rule}' ''')
        # Удаляем роль

    conn.commit()

    #cursor = conn.cursor()
    cursor.execute(f"SELECT rule FROM user_rule WHERE user_tg_id = '{user_id}'")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    user = cursor.fetchone()
    result = dict(zip(columns, user)) if user else None

    return result


# >> ============= настройка ===================


# << ============= оплата бота ===================
def append_fill_wallet_line(user_tg_id: int, type_line: str, code:str, description: str, amount:float, conn=None):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = cursor.fetchone()
    result = dict(zip(columns, row))

    cursor.execute(f"""INSERT INTO wallet_log (user_tg_id, type, code, description, balance, total_spent_month, total_spent, next_write_off_date) 
                         VALUES ('{user_tg_id}', 
                            '{type_line}', 
                            '{code}', 
                            '{description}', 
                            '{result['balance'] + amount}', 
                            '{result['total_spent_month']}',
                            '{result['total_spent']}',
                            '{result['next_write_off_date']}');
                        """)
    conn.commit()

    cursor.execute(f"SELECT * FROM wallet_log ORDER BY id DESC LIMIT 1")
    columns = [column[0] for column in cursor.description]

    # Получение результатов в виде списка словарей
    row = cursor.fetchone()
    result = dict(zip(columns, row))
    return result


def get_admins_id(conn=None):
    cursor = conn.cursor()
    cursor.execute(f'''SELECT user_tg_id FROM admins;''')
    admin_list = list(cursor.fetchall())

    return admin_list
# >> ============= оплата бота ===================

if __name__ == '__main__':
    get_admin(123)