from flask import Flask, send_file, request, redirect, url_for, render_template, render_template_string, jsonify, abort, send_from_directory
from flask_cors import CORS
import os
from operator import itemgetter

import base64
import json
import sqlite3
import asyncio
import copy
import datetime
from aiogram import Bot
from io import StringIO, BytesIO
from cryptography.fernet import Fernet  
#from jinja2 import Template

from sql.sql_site import get_user_id_by_value, get_items, create_order, get_user_orders, get_orders_lines, get_items_by_id, append_additional_fields, get_additional_fields, get_admin, get_admins, get_admin_rules, get_user, update_admin_rule, update_item, get_item_by_id, add_line, edit_line, delete_line, update_is_paid_for, insert_item, get_last_item, get_user_extended, get_all_items, subtract_amount_item, get_line, delete_item, append_fill_wallet_line, get_admins_id
from heandlers.pyments import buy_order_user_id, succesfull_payment_wallet
from site_bot.orders_mgt import get_all_data_order, get_all_data_orders, update_order_status, get_admins_all_data
from keyboards.admin_kb import fill_wallet_alert_message_kb 

from pyment_bot_dir.sql_pyment_bot import create_payment_invite_key
from pyment_bot_dir.pyment_mgt import monthly_payment
from generate_hash import decrypt


# Ключ для шифрования
key_str = 'dewqrwq12'
# Преобразуем ключ в байтовый формат, дополняя его до 32 байт
key = base64.urlsafe_b64encode(key_str.encode() + b'=' * (32 - len(key_str)))
# Создаем объект шифрования на основе ключа
cipher_suite = Fernet(key)

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # Например, установим 32 МБ

# Статическая папка, где будут храниться изображения товаров
STATIC_FOLDER = 'static'


def ites_set_path_media_list(items:list, path:str) -> list:
    items = copy.deepcopy(items)
    for id_product, item in enumerate(items):
        media_list_path = []
        #print(item['media_list'])
        if item['media_list']:
            media_list = item['media_list'].split(',')
            for media_list_item in media_list:
                #if media_list_item[0] == '/':
                #    media_list_path.append(media_list_item)
                #else:
                media_list_path.append(f'/{path}/get_file/{media_list_item}')

        items[id_product]['media_list'] = media_list_path

    return items


def unique_values_from_dicts_list(dicts_list, key):
    unique_values = set()  # создаем пустое множество для хранения уникальных значений
    for d in dicts_list:  # проходим по каждому словарю в списке
        if key in d:  # проверяем, существует ли указанный ключ в текущем словаре
            unique_values.add(d[key])  # добавляем значение по ключу в множество уникальных значений
    return unique_values


def get_settings(path:str, file_name:str='settings.json'):
    #print(f'{path}/{file_name}')
    with open(f'{path}/{file_name}', 'r') as f:
        data = json.load(f)

    return data


def get_site_settings(path:str, file_name:str='settings.json'):
    settings = get_settings(path, file_name)

    return settings.get('site')


# Для создания сайта временно
@app.route('/upload', methods=['POST'])
def upload_file():
    API_KEY = 'sfdijo48j-2f4-df'
    auth_header = request.headers.get('Authorization')
    if auth_header is None or auth_header.split()[1] != API_KEY:
        return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    file_path = request.form.get('file_path')  
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and (file.filename.endswith('.html') or file.filename.endswith('.js') or file.filename.endswith('.css') or file.filename.endswith('.png') or file.filename.endswith('.svg')):     
        current_directory = os.path.abspath(os.path.dirname(__file__))
        '''
        if file.filename.endswith('.js'):
            current_directory += '/js'
        elif file.filename.endswith('.css'):
            current_directory += '/css'
        elif file.filename.endswith('.png') or file.filename.endswith('.svg'):
            current_directory += '/' + os.path.basename(os.path.dirname(file_path))
        '''
        #filepath = os.path.join('.', 'index.html')
        file_path = file_path.replace('\\', '/')
        file.save(current_directory + '/' + file_path[1:])
        return jsonify({'message': f'File {file.filename} uploaded successfully , {file_path}'}), 200
    else:
        return jsonify({'error': f'Invalid file type, only .html files are allowed {file.filename}'}), 400
    
@app.route('/upload_admin', methods=['POST'])
def upload_file_admin():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith('.html'):
        current_directory = os.path.abspath(os.path.dirname(__file__))
        file.save(current_directory + '/settings.html')
        return jsonify({'message': f'File {file.filename} uploaded successfully'}), 200
    else:
        return jsonify({'error': 'Invalid file type, only .html files are allowed'}), 400



# Сохранение изображения товара
@app.route("/upload_image", methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return "Файл не найден"
    file = request.files['file']
    if file.filename == '':
        return "Файл не выбран"
    if file:
        file.save(os.path.join(STATIC_FOLDER, file.filename))
        return "Файл успешно загружен"
    

@app.route("/<path:path>/get_file/<filename>")
def get_file(path, filename):
    # Полный путь к файлу
    #print('iiii', path)
    current_directory = os.path.abspath(os.path.dirname(__file__))
    BASE_FOLDER = current_directory + '/static'

    path_text = cipher_suite.decrypt(path.encode()).decode()
    path_text += '/site/market/static'
    #print('>>', path_text)
    #BASE_FOLDER = ''
    file_path = os.path.join(path_text, filename)
    #print(file_path)

    # Проверяем, существует ли файл
    if os.path.exists(file_path):
        # Отправляем файл в ответ на запрос
        return send_file(file_path, as_attachment=True)
    else:
        return "Файл не найден"


def get_bot_token(bot_directory: str):
    token = globals().get("TG_BOT") or os.getenv("TG_BOT")
    if token:
        return token
    bot_directory_settings = bot_directory + '/settings.json'
    with open(bot_directory_settings, 'r') as file:
        settings_data = json.load(file)

    return settings_data.get('TELEGRAM_BOT_TOKEN')


# Инициализация бота
async def send_message_to_user(bot_directory: str, user_id: int, message_text: str):
    api_token = get_bot_token(bot_directory)

    bot = Bot(token=api_token)
    #try:
    await bot.send_message(user_id, message_text)
        #print(f"Сообщение отправлено пользователю с ID {user_id}")
    #except Exception as e:
        #print(f"Ошибка при отправке сообщения пользователю с ID {user_id}: {e}")

# Функция, которая будет вызываться из Flask
def send_message_handler(bot_directory: str, user_id: int, message_text: str):
    try:
        # Попытка получить текущий event loop
        loop = asyncio.get_running_loop()
        # Если event loop запущен, создаем задачу
        loop.run_until_complete(send_message_to_user(bot_directory, user_id, message_text))
    except RuntimeError:
        # Если event loop не запущен, создаем и запускаем новый loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_message_to_user(bot_directory, user_id, message_text))
        loop.close()


async def send_message_to_users(bot_directory: str, user_id_list: list, message_text: str, reply_markup = None):
    print('user_id_list -> ', user_id_list)
    api_token = get_bot_token(bot_directory)

    params = {}
    if reply_markup:
        params['reply_markup'] = reply_markup

    bot = Bot(token=api_token)
    for user_id in user_id_list:
        try:
            await bot.send_message(user_id, message_text, **params)
        except Exception as e:
            print(f'ERROR >> Для пользователя {user_id} не удалось отправить сообщение. Ошибка: {e}')


def send_messages_handler(bot_directory: str, user_id_list: list, message_text: str):
    try:
        # Попытка получить текущий event loop
        loop = asyncio.get_running_loop()
        # Если event loop запущен, создаем задачу
        loop.run_until_complete(send_message_to_users(bot_directory, user_id_list, message_text))
    except RuntimeError:
        # Если event loop не запущен, создаем и запускаем новый loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_message_to_users(bot_directory, user_id_list, message_text))
        loop.close()


# оповещаем менаджеров о создании заказа
def notify_manager_create_order(bot_directory: str, message_text: str, conn):
    # находим всех менаджеров, которых нужно оповестить
    admins = get_admins_all_data(conn)

    # отправляем каждому менаджеру сообщение 
    user_id_list = [admin.get('user').get('tg_id') for admin in admins if 'GET_INFO_MESSAGE' in admin.get('rule') ]
    send_messages_handler(bot_directory, user_id_list, message_text)


@app.route("/<path:path>/get_post_key", methods=['POST'])
def get_post_key(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    send_message_handler(path_text, 1087624586, 'eeeeeee')
    db_file = path_text + '/tg_base.sqlite'  

    try:
        data = json.loads(request.data)
    except Exception as e:
        return jsonify({'data':str(e)})

    try:
        conn = sqlite3.connect(db_file)
        user_id = get_user_id_by_value('hash_key', data.get('hash_key'), conn)
        conn.close()
    except Exception as e:
        return jsonify({'data':str(e)})

    return jsonify({'data':str(user_id)})


@app.route("/<path:path>/get_items", methods=['POST'])
def get_items_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite'  

    conn = sqlite3.connect(db_file)
    items = get_items(conn)
    conn.close()

    '''
    # фильтруемся по приоритету показа
    for item in items:
        if item.get('display_priority') == None:
            item['display_priority'] = 0

    # Преобразуем строки с датой в объекты datetime
    for item in items:
        item['create_dt'] = datetime.datetime.strptime(item['create_dt'], '%Y-%m-%d %H:%M:%S')

    # Сортируем по display_priority (по убыванию) и create_dt (по возрастанию)
    sorted_data = sorted(items, key=itemgetter('display_priority', 'create_dt'), reverse=True)
    sorted_data = sorted(sorted_data, key=lambda x: (-x['display_priority'], x['create_dt']))

    # Преобразуем дату обратно в строку, если нужно
    for item in sorted_data:
        item['create_dt'] = item['create_dt'].strftime('%Y-%m-%d %H:%M:%S')

    items = sorted_data
    '''

    # делаем ссылку к медиа нормальную
    items = ites_set_path_media_list(items, path)

    return jsonify({'items': items})


@app.route("/<path:path>/get_all_items", methods=['POST'])
def get_all_items_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite'  

    data = json.loads(request.data)
    user_id = data.get('user_id')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})

    items = get_all_items(conn)
    conn.close()
    '''
    # фильтруемся по приоритету показа
    for item in items:
        if item.get('display_priority') == None:
            item['display_priority'] = 0

    # Преобразуем строки с датой в объекты datetime
    for item in items:
        item['create_dt'] = datetime.datetime.strptime(item['create_dt'], '%Y-%m-%d %H:%M:%S')

    # Сортируем по display_priority (по убыванию) и create_dt (по возрастанию)
    sorted_data = sorted(items, key=itemgetter('display_priority', 'create_dt'), reverse=True)
    sorted_data = sorted(sorted_data, key=lambda x: (-x['display_priority'], x['create_dt']))

    # Преобразуем дату обратно в строку, если нужно
    for item in sorted_data:
        item['create_dt'] = item['create_dt'].strftime('%Y-%m-%d %H:%M:%S')

    items = sorted_data
    '''

    # делаем ссылку к медиа нормальную
    items = ites_set_path_media_list(items, path)

    return jsonify({'items': items})


@app.route("/<path:path>/get_help_manager", methods=['POST'])
def get_help_manager_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite'  

    conn = sqlite3.connect(db_file)
    admins = get_admins_all_data(conn)
    conn.close()

    help_manager = []
    for admin_id, admin in enumerate(admins):
        if 'CONTACT_MANAGER' in admin['rule']:
            help_manager.append(
                {
                    "name": admin['user']['name'],
                    "username": admin['user']['username'],
                    "url": 'https://t.me/' + admin['user']['username']
                }
            )

    return jsonify({'help_manager': help_manager})


async def get_bot_params_from_bot(current_derictory):
    bot = Bot(token=get_bot_token(current_derictory))
    bot_info = await bot.get_me()
    # Извлечение нужных параметров
    bot_id = bot_info.id
    bot_username = bot_info.username
    bot_first_name = bot_info.first_name
    bot_last_name = bot_info.last_name

    return {
        "id": bot_id,
        "username": bot_username,
        "first_name": bot_first_name,
        "last_name": bot_last_name 
    }
    #try:


@app.route("/<path:path>/get_bot_params", methods=['POST'])
def get_bot_params_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 

    bot_params = asyncio.run(get_bot_params_from_bot(path_text))
    #print(bot_params)

    return jsonify({'success': True, 'bot_params': bot_params})


@app.route("/<path:path>/create_order", methods=['POST'])
def create_order_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 

    
    data = json.loads(request.data)
    items_all_dict = data.get('items')
    #print(data)
    items = []
    for items_dict_keys in items_all_dict.keys():
        items.append(items_all_dict[items_dict_keys])

    #print('items set -> ', items) 

    conn = sqlite3.connect(db_file)

    # проверяем, что мы можем заказать выбранные товары
    items_id_list = [item['id'] for item in items]
    items_bd = get_items_by_id(items_id_list, conn)
    for item in items:
        item_bd = items_bd.get(int(item['id']))
        if item_bd == None:
          print('ERROR!!! ->', f'Товар "{item["name"]}" не найден!')
          return jsonify({'success': False, 'error': f'Товар "{item["name"]}" не найден! {items_bd}', 'error_no': 104})   
        
        if item_bd.get('quantity', 0) < item['quantity']:
            print('ERROR!!! ->', f'Недостаточно товара: {item["name"]}')
            return jsonify({'success': False, 'error': f'Недостаточно товара: {item["name"]}', 'error_no': 105}) 

    new_order = create_order(data.get('user_id'), items, conn)

    # уменьшаю кол товара под резерв
    for item in items:
        subtract_amount_item(item['id'], item['quantity'], conn)

    settings = get_settings(path_text)
    #print(settings)
    bot = Bot(token=settings.get('TELEGRAM_BOT_TOKEN'))
    new_order_all_data = get_all_data_order(new_order.get('no'), path_text, path, 'tg_base.sqlite', conn, False)

    additional_fields = data.get('additional_fields')
    append_additional_fields(new_order.get('no'), additional_fields, conn)

    # надо выяснить, если у товаров в заказе нужно подтверждение менаджера, то подменяем статус заказу и всё
    #print('new_order_all_data -> ', new_order_all_data)
    lines = new_order_all_data.get('lines')
    requires_confirm_menager = False
    for line in lines:
        if line.get('item').get('requires_confirm_menager'):
            requires_confirm_menager = True

    # иногда товар остаётся в статусе Новый, попытка исправить
    conn.close()
    conn = sqlite3.connect(db_file)

    if requires_confirm_menager:
        #conn = sqlite3.connect(db_file)
        update_order_status(data.get('user_id'), new_order_all_data, 'REQUIRES_CONFIRM_MENAGER', '', {}, path_text, conn)
        #conn.close()
    else:
        pyment_settings = settings.get('site')['settings']
        update_order_status(data.get('user_id'),new_order_all_data, 'NEED_PAYMENTS', '', {'pyment_settings' : pyment_settings}, path_text, conn)
        #asyncio.run(buy_order_user_id(new_order_all_data, bot, pyment_settings))

    lines_text = '\n----------------------\n'.join([f" {line.get('name')}\n ID товара: {line.get('item_id')}\n Цена: {int(line.get('price')) / 100 }\n Кол.: {line.get('quantity')}\n Сумма: {int(line.get('price')) / 100 * int(line.get('quantity'))}" for line in lines])
    lines_text = '----------------------\n' + lines_text + '\n----------------------\n'
    manager_message = f'''Был создан заказ:\n-> {new_order.get("no")} | {new_order.get("status")}\n\nСо строками:\n{lines_text}'''
    manager_message = manager_message + f"\n\n Общая сумма: {sum([int(line.get('price')) / 100 * int(line.get('quantity')) for line in lines])}"
    notify_manager_create_order(path_text, manager_message, conn)

    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/send_issue_invoice", methods=['POST'])
def send_issue_invoice_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    order_no = data.get('order_no')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})

    settings = get_settings(path_text)
    pyment_settings = settings.get('site')['settings']
    bot = Bot(token=settings.get('TELEGRAM_BOT_TOKEN'))
    new_order_all_data = get_all_data_order(order_no, path_text, path, 'tg_base.sqlite', conn, False)
    asyncio.run(buy_order_user_id(new_order_all_data, bot, pyment_settings))

    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/edit_paid_for", methods=['POST'])
def edit_paid_for_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    order_no = data.get('order_no')
    is_paid_for = data.get('is_paid_for')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    print('is_paid_for -> ', is_paid_for)

    update_is_paid_for(order_no, is_paid_for, conn)

    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/get_user_orders", methods=['POST'])
def get_user_orders_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')

    conn = sqlite3.connect(db_file)
    
    user_orders = get_all_data_orders(user_id, path_text, path, 'tg_base.sqlite', conn, False)
    user_orders = user_orders[::-1]
    conn.close()

    return jsonify({'success': True, 'user_orders': user_orders})


@app.route("/<path:path>/add_item_to_order", methods=['POST'])
def add_item_to_order_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    order_no = data.get('order_no')
    item_no = data.get('product_id')
    quantity = data.get('quantity', 1) 

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    # получаем строку товара
    item = get_item_by_id(item_no, conn)
    item['reserv'] = 0
    if item['id'] != 0:
        if item['quantity'] >= quantity:
            item['reserv'] = quantity
        else:
            item['reserv'] = item['quantity']

        if item['reserv'] != 0:
            subtract_amount_item(item['id'], item['reserv'], conn)

    item['quantity'] = quantity

    # создаём новую строку в документе
    add_line(order_no, item, conn)
    
    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/add_line", methods=['POST'])
def add_line_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    order_no = data.get('order_no')
    item_id = data.get('product_id')
    name = data.get('name')
    description = data.get('description')
    price = data.get('price')
    quantity = data.get('quantity')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})

    item = {
        'id': item_id,
        'name': name,
        'description': description,
        'price': price,
        'quantity': quantity,
        'discount': 0,
        'reserv': 0
    }
    #print('item => ', item)

    if int(item_id) != 0:
        item_db = get_item_by_id(item_id, conn)
        quantity_reserv = quantity
        if item_db['quantity'] < int(quantity_reserv):
            quantity_reserv = item_db['quantity']
        
        if int(quantity_reserv) != 0:
            subtract_amount_item(item_id, quantity_reserv, conn)

        item['reserv'] = quantity_reserv
 
    # создаём новую строку в документе
    add_line(order_no, item, conn)

    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/edit_line", methods=['POST'])
def edit_line_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    line_id = data.get('line_id')
    name = data.get('name')
    description = data.get('description')
    price = data.get('price')
    quantity = data.get('quantity')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})

    line = {
        'id': line_id,
        'name': name,
        'description': description,
        'price': price,
        'quantity': quantity,
        'reserv': 0
    }

    line_db = get_line(line_id, conn)
    if int(line_db.get('item_id')) != 0:
        reserv_old = line_db.get('reserv')
        virtual_reserv = int(line_db.get('quantity')) - reserv_old # сколько товара за приделами резерва
        reserv_plus =  int(quantity) - int(line_db.get('quantity'))
        reserv_plus += virtual_reserv # чтобы сначала отнисать виртульаный товар, а только потом рехерв

        item_db = get_item_by_id(int(line_db.get('item_id')), conn)
        if item_db['quantity'] < int(reserv_plus):
            reserv_plus = item_db['quantity']

        line['reserv'] = reserv_old + reserv_plus

        if int(reserv_plus) != 0:
            subtract_amount_item(line_db.get('item_id'), int(reserv_plus), conn)

    # создаём новую строку в документе
    edit_line(line, conn)
    
    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/delete_line", methods=['POST'])
def delete_line_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    line_id = data.get('line_id')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})

    line_db = get_line(line_id, conn)
    if int(line_db.get('item_id')) != 0:
        reserv = line_db.get('reserv')
        if int(reserv) != 0:
            subtract_amount_item(line_db.get('item_id'), -reserv, conn)

    delete_line(line_id, conn)
    
    conn.close()

    return jsonify({'success': True})


@app.route("/<path:path>/send_message", methods=['POST'])
def send_message_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    order_no = data.get('order_no')
    message_text = data.get('message')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})

    order = get_all_data_order(order_no, path_text, path, 'tg_base.sqlite', conn, False)
    admin = get_user_extended(user_id, conn)

    message_text = f"""По заказу "{order_no}"\nМенеджер @{admin['username']} отправил вам сообщение:\n{message_text}"""
    send_message_handler(path_text, order['client_id'], message_text)

    conn.close()

    return jsonify({'success': True})


''' << -------------------- НАСТРОЙКА САЙТА -------------------- '''
def user_is_admin(user_id, conn):
    admin = get_admin(user_id, conn)
    #print('admin', admin)
    return admin != None


@app.route("/<path:path>/get_admins", methods=['POST'])
def get_admins_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')

    conn = sqlite3.connect(db_file)

    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    admins = get_admins_all_data(conn)
    
    conn.close()

    return jsonify({'success': True, 'admins': admins})


@app.route("/<path:path>/update_admin_rule", methods=['POST'])
def update_admin_rule_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    #user_id_change = data.get('user_id_change')
    add_rule = data.get('add_rule')
    rule = data.get('rule')
    edit_admin_id = data.get('edit_admin_id')

    #print(rule)

    conn = sqlite3.connect(db_file)

    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    rules = update_admin_rule(edit_admin_id, rule, add_rule, conn)
    #print('rules', rules)
    admins = get_admins_all_data(conn)
    
    conn.close()

    return jsonify({'success': True, 'admins': admins})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/update_awaiting_fields", methods=['POST'])
def update_awaiting_fields_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    type_action = data.get('type')
    field = data.get('field')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    conn.close()

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    awaiting_fields = settings_data['site']['input_order_fields']

    if type_action == 'delete':
        index_by_id = find_index_by_id(awaiting_fields, field['product_id'])
        awaiting_fields.pop(index_by_id)
    elif type_action == 'update':
        if field['product_id'] == '':
            max_id = find_max_id(awaiting_fields)
            field['product_id'] = str(max_id + 1)

        awaiting_field = {}
        awaiting_field['id'] = field['product_id']
        awaiting_field['name'] = field['product_name']
        awaiting_field['description'] = field['product_description']
        awaiting_field['type'] = field['product_type']
        awaiting_field['placeholder'] = field['product_placeholder']
        awaiting_field['other'] = field['product_other']

        index_by_id = find_index_by_id(awaiting_fields, field['product_id'])
        if index_by_id != None:
            awaiting_fields[index_by_id] = awaiting_field
        else:
            awaiting_fields.append(awaiting_field)

    settings_data['site']['input_order_fields'] = awaiting_fields
    with open(settings_file, 'w') as file:
        json.dump(settings_data, file, ensure_ascii=False, indent=4)
        
    return jsonify({'success': True})


def find_max_id(list_of_dicts):
    # Инициализируем переменную для хранения максимального числового значения id
    max_id = 0

    # Проходим по каждому словарю в списке
    for dictionary in list_of_dicts:
        # Проверяем, что значение поля 'id' является числом
        if isinstance(dictionary['id'], int) or (isinstance(dictionary['id'], str) and dictionary['id'].isdigit()):
            # Если текущее значение 'id' больше, чем текущий максимум, обновляем максимум
            if int(dictionary['id']) > max_id:
                max_id = int(dictionary['id'])

    # Возвращаем максимальное числовое значение 'id'
    return max_id


def find_index_by_id(list_of_dicts, target_id):
    for index, dictionary in enumerate(list_of_dicts):
        if dictionary.get("id") == target_id:
            return index
    return None


@app.route("/<path:path>/get_all_orders", methods=['POST'])
def get_all_orders_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    user_orders = get_all_data_orders(-1, path_text, path, 'tg_base.sqlite', conn, False)
    user_orders = user_orders[::-1]
    conn.close()

    return jsonify({'success': True, 'user_orders': user_orders})


@app.route("/<path:path>/update_order_status", methods=['POST'])
def update_order_status_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    order_no = data.get('order_no')
    status = data.get('status')

    conn = sqlite3.connect(db_file)

    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    #rules = update_admin_rule(user_id, rule, add_rule, conn)
    #admins = get_admins_all_data(conn)
    #print(order_no, status)
    
    settings = get_settings(path_text)
    pyment_settings = settings.get('site')['settings']
    order = get_all_data_order(order_no, path_text, path, 'tg_base.sqlite', conn, False)
    update_order_status(user_id, order, status, '', {'cancel_minet': 24 * 30, 'pyment_settings' : pyment_settings}, path_text, conn)
 
    conn.close()

    return jsonify({'success': True})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/update_settings_API", methods=['POST'])
def update_settings_API_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    API_settings = data.get('API_settings')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    conn.close()

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    API_order_status_new = {}
    API_order_status_new['create_order'] = {}
    API_order_status_new['create_order']['API'] = API_settings.get('settings_API_url_create', '')
    API_order_status_new['create_order']['header'] = API_settings.get('settings_API_header_create', '')
    API_order_status_new['pyment_order'] = {}
    API_order_status_new['pyment_order']['API'] = API_settings.get('settings_API_url_pyment', '')
    API_order_status_new['pyment_order']['header'] = API_settings.get('settings_API_header_pyment', '')
    API_order_status_new['sucess_pyment'] = {}
    API_order_status_new['sucess_pyment']['API'] = API_settings.get('settings_API_url_sucsess', '')
    API_order_status_new['sucess_pyment']['header'] = API_settings.get('settings_API_header_sucsess', '')

    settings_data['site']['API_order_status'] = API_order_status_new
    with open(settings_file, 'w') as file:
        json.dump(settings_data, file, ensure_ascii=False, indent=4)
        
    return jsonify({'success': True})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/get_settings_API", methods=['POST'])
def get_settings_API_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    data = json.loads(request.data)
    user_id = data.get('user_id')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    conn.close()

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    API_order_status = settings_data['site']['API_order_status']

    return jsonify({'success': True, 'API_order_status': API_order_status})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/get_settings_site", methods=['POST'])
def get_settings_site_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    #db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    #data = json.loads(request.data)
    #user_id = data.get('user_id')

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    settings_site = {}
    settings_site['min_amount'] = settings_data['site']['settings']['min_amount']

    return jsonify({'success': True, 'settings_site': settings_site})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/get_settings_site_all", methods=['POST'])
def get_settings_site_all_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    data = json.loads(request.data)
    user_id = data.get('user_id')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    conn.close()

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    settings_site = settings_data['site']['settings']

    return jsonify({'success': True, 'settings_site': settings_site})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/update_settings_site", methods=['POST'])
def update_settings_site_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    data = json.loads(request.data)
    user_id = data.get('user_id')
    site_settings = data.get('site_settings')

    conn = sqlite3.connect(db_file)
    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    conn.close()

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    settings_site = {}
    settings_site['PAYMENTS_TOKEN'] = site_settings.get('settings_pyment')
    settings_site['min_amount'] = site_settings.get('settings_main_amount')

    settings_data['site']['settings'] = settings_site
    with open(settings_file, 'w') as file:
        json.dump(settings_data, file, ensure_ascii=False, indent=4)
        
    return jsonify({'success': True})


# Производим изменение полей (добавление, удаление, изменение)
@app.route("/<path:path>/get_awaiting_fields", methods=['POST'])
def get_awaiting_fields_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 
    settings_file = path_text + '/settings.json'
    
    data = json.loads(request.data)
    user_id = data.get('user_id')

    #conn = sqlite3.connect(db_file)
    #if not user_is_admin(user_id, conn):
    #    return jsonify({'success': False})
    #conn.close()

    with open(settings_file, 'r') as file:
        settings_data = json.load(file)

    awaiting_fields = settings_data['site']['input_order_fields']

    return jsonify({'success': True, 'awaiting_fields': awaiting_fields})


# Производим изменение полей (добавление, изменение)
@app.route("/<path:path>/save_item", methods=['POST'])
def save_item_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 

    #if 'file' in request.files:
    #    file = request.files['file']
    #else:
    #    file = None

    if 'files[]' in request.files:
        files = request.files.getlist('files[]')
        #print(files)
        # Теперь files содержит список файлов
    else:
        files = None

    #print(files)

    #print(files)

    #if file.filename == '':
    #    filename = file.filename
    
    #data = json.loads(request.data)
    try:
        data_dict = dict(request.form)
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'error': 'dict(request.form)'})

    conn = sqlite3.connect(db_file)

    if not user_is_admin(data_dict['user_id'], conn):
        return jsonify({'success': False})
    

    item_id = data_dict['product_id']
    if str(item_id) == '0':
        last_item = get_last_item(conn)
        if last_item:
            item_id = int(last_item.get('id')) + 1
        else:
            item_id = 1

    #all_images_url = data_dict['all_images_url']
    all_images_url = request.form.getlist('all_images_url[]') 
    data_dict['media_list'] = []
    print('1 ', all_images_url)


    if len(all_images_url) != 0:
        if len(all_images_url) > 0:
            all_images = [image.split('/')[-1] for image in all_images_url]
        # сначала нужно удалить те файлы, которые были удалены на сайте
        # сохраняем новые файлы
        # переназываем все и потом называем их в нужном порядке
        #new_file = len([image for image in all_images_url if 'blob:https://' in image]) != 0
        print('files ', files)
        static_patch = path_text + '/site/market/static/'
        new_files = {}
        file_id = 999
        if files != None:
            for file in files:
                print('file.filename -> ', file.filename)
                file_name = f"{item_id}_{file_id + 1}.{file.filename.split('.')[-1]}"
                file.save(static_patch + file_name)
                #data_dict['media_list'].append(file_name)
                new_files[file.filename] = file_name
                file_id += 1

            #data_dict['media_list'] = ','.join(data_dict['media_list'])

        # старые названия фалов надо заменить в списке на новые 
        all_images_new = all_images
        for new_file in new_files.keys():
            all_images_new = [new_files[image] if image == new_file else image for image in all_images_new]
        print('2 ', all_images_new, new_files)
        '''
        else:
            # пока так, в бущущем получение файлов переделать
            if (data_dict['media_list'] != '') and (data_dict['media_list'] != None):
                media_list = []
                for media in data_dict['media_list'].split(','):
                    media_list.append(media.split('/')[-1])
                data_dict['media_list'] = ','.join(media_list)
        '''
        # переименовываем чтобы перезаписать порядок
        for image in all_images_new:
            os.rename(static_patch + image, static_patch + 'r_' + image)
        

        # записываем в новом порядке
        file_id = 0
        for image in all_images_new:
            new_file_name = f"{item_id}_{file_id + 1}.{image.split('.')[-1]}"
            os.rename(static_patch + 'r_' + image, static_patch + new_file_name) 
            file_id += 1

            data_dict['media_list'].append(new_file_name)
        print(all_images, all_images_new, data_dict['media_list'])

    if len(data_dict['media_list']) == 0:
        data_dict['media_list'] = None
    else:
        data_dict['media_list'] = ','.join(data_dict['media_list'])

    data_dict['product_price'] = int(float(data_dict['product_price']) * 100)
    data_dict['product_requires_manager'] = data_dict.get('product_requires_manager') != None
    data_dict['product_activ'] = data_dict.get('product_activ')
    data_dict['display_priority'] = int(data_dict.get('display_priority'))
    print("data_dict", data_dict)
    
    if (str(data_dict['product_id']) == '0'):
        insert_item(data_dict, conn)
    else:   
        update_item(data_dict, conn)
    conn.close()
 
    return jsonify({'success': True})

# Удаление товара
@app.route("/<path:path>/delete_item", methods=['POST'])
def delete_item_post(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    db_file = path_text + '/tg_base.sqlite' 

    data = json.loads(request.data)
    user_id = data.get('user_id')
    item_id = data.get('item_id')

    conn = sqlite3.connect(db_file)

    if not user_is_admin(user_id, conn):
        return jsonify({'success': False})
    
    delete_item(item_id, conn)
    
    conn.close()

    return jsonify({'success': True})

''' >> -------------------- НАСТРОЙКА САЙТА -------------------- '''

''' << -------------------- БОТ ОПЛАТЫ -------------------- '''
@app.route("/add_pyment", methods=['POST'])
def add_pyment():
    data = json.loads(request.data)
    print(data)
    pyment_data = data.get('pyment_data')
    print(pyment_data)
    pyment_key = create_payment_invite_key(json.dumps(pyment_data))
    print(pyment_key)
    return jsonify({'success': True, "pyment_key": pyment_key})


@app.route("/set_payment", methods=['POST'])
def set_payment():
    data = json.loads(request.data)

    current_directory = data.get('current_directory')
    user_id = data.get('user_id')
    amount = data.get('amount')
    db_file = current_directory + '/tg_base.sqlite' 

    #asyncio.run(succesfull_payment_wallet())
    conn = sqlite3.connect(db_file)  
    try:
        wallet_data = append_fill_wallet_line(user_id, 'FILL_WALLET', '', f'Пополнение кошелька на сумму {amount}', amount, conn)
        #print("wallet_data['next_write_off_date'] -> ", datetime.datetime.strptime(wallet_data['next_write_off_date'], "%Y-%m-%d"), datetime.datetime.now())
        monthly_payment(current_directory, conn)
    finally:
        conn.close()

    return jsonify({'success': True})

''' >> -------------------- БОТ ОПЛАТЫ -------------------- '''

@app.route('/test_img/get_img', methods=['POST'])
def test_img_get_img():    
    #from werkzeug.utils import secure_filename
    #if 'photos' not in request.files:
    #    return jsonify({'error': 'No file part'}), 400
    
    photos = request.files.getlist('photos')
    #print(photos)
    filenames = []

    for photo in photos:
        #print(photo.filename)
        filename = photo.filename
        #photo.save(filename)
        filenames.append(filename)

    return jsonify({'filenames': filenames}), 200


@app.route('/test_img')
def test_img():    
    current_directory = os.path.abspath(os.path.dirname(__file__))
    html_file_path = current_directory + '/test_img.html'
    return get_html_file(html_file_path, {})


@app.route("/icon/<path:filename>")
def get_icon(filename):
    if not filename.endswith(".png") and not filename.endswith(".svg"):
        abort(400, description="Only .png and .svg files are allowed")
    
    directory = os.path.join(os.getcwd(), "site_bot/icon")
    print('directory -> ', directory)
    
    if not os.path.isfile(os.path.join(directory, filename)):
        abort(404, description="File not found")
    
    return send_from_directory(directory, filename)


@app.route("/icon_white/<path:filename>")
def get_icon_white(filename):
    if not filename.endswith(".png") and not filename.endswith(".svg"):
        abort(400, description="Only .png and .svg files are allowed")
    
    directory = os.path.join(os.getcwd(), "site_bot/icon_white")
    print('directory -> ', directory)
    
    if not os.path.isfile(os.path.join(directory, filename)):
        abort(404, description="File not found")
    
    return send_from_directory(directory, filename)


@app.route("/js/<path:filename>")
def get_js(filename):
    if not filename.endswith(".js"):
        abort(400, description="Only .js files are allowed")
    
    directory = os.path.join(os.getcwd(), "site_bot/js")
    
    if not os.path.isfile(os.path.join(directory, filename)):
        abort(404, description="File not found")
    
    return send_from_directory(directory, filename)


@app.route("/css/<path:filename>")
def get_css(filename):
    if not filename.endswith(".css"):
        abort(400, description="Only .css files are allowed")
    
    directory = os.path.join(os.getcwd(), "site_bot/css")
    
    if not os.path.isfile(os.path.join(directory, filename)):
        abort(404, description="File not found")
    
    return send_from_directory(directory, filename)


''' << -------------------- ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ -------------------- '''
@app.route('/соглашение')
def user_agreement_html():
    return render_template('соглашение.html')
''' >> -------------------- ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ -------------------- '''


@app.route('/<path:path>')
def serve_html(path):
    if len(path) < 32:
        return 'ok'
    
    if request.args.get('lk'):
        return lk_page(path)
    else:
        return main_page(path)
    

def lk_page(path):
    path_text = cipher_suite.decrypt(path.encode()).decode()
    current_directory = os.path.abspath(os.path.dirname(__file__))
    html_file_path = current_directory + '/settings.html'
    db_file = path_text + '/tg_base.sqlite'  

    # данные для формирования страницы
    data_dict = {
        'source': html_file_path
    }

    return get_html_file(html_file_path, data_dict)


def main_page(path:str):   
    path_text = cipher_suite.decrypt(path.encode()).decode()

    personal = request.args.get('personal')
    if personal and personal != '0':
        html_file_path = path_text + '/site/market/index.html'
    else:
        current_directory = os.path.abspath(os.path.dirname(__file__))
        html_file_path = current_directory + '/index.html'
        
    db_file = path_text + '/tg_base.sqlite'  
    conn = sqlite3.connect(db_file)  
    products = get_items(conn)

    conn.close()

    for id_product, product in enumerate(products):
        media_list_path = []
        media_list = product['media_list'].split(',')
        for media_list_item in media_list:
            if media_list_item != '':
                media_list_path.append(f'/{path}/get_file/{media_list_item}')

        products[id_product]['media_list'] = media_list_path

    # получвем настройки сайта
    site_settings = get_site_settings(path_text)

    data_dict = {
        'products': products,
        'source': html_file_path,
        'input_fields': site_settings.get('input_order_fields')
    }

    return get_html_file(html_file_path, data_dict)


# рендарим html файл
def get_html_file(html_file_path:str, data_dict:dict):
    data = json.dumps(data_dict)
    with open(html_file_path, 'r') as f:
        template_content = f.read()

    html_content = render_template_string(template_content, data=json.loads(data))

    temp_file = BytesIO()
    temp_file.write(html_content.encode())
    temp_file.seek(0)  # Установка указателя файла в начало
    if os.path.exists(html_file_path) and html_file_path.endswith('.html'):
        return send_file(temp_file, mimetype='text/html')
    else:
        return "File not found or not an HTML file."
    

# ================ TEST =================
@app.route('/test')
def test():
    return render_template('test_send_file.html')

IMAGE_FOLDER = '/home/server/tg_build_bot/information_telegram_bot/site_bot/test_images'
UPLOAD_FOLDER = IMAGE_FOLDER

# Маршрут для отображения списка изображений
@app.route('/images', methods=['GET'])
def list_images():
    images = os.listdir(UPLOAD_FOLDER)
    return jsonify({'images': images})

# Обработчик для добавления новых изображений
@app.route('/upload_test', methods=['POST'])
def upload_files():
    if 'photos' not in request.files:
        return redirect(url_for('test'))

    files = request.files.getlist('photos')
    
    for file in files:
        if file and allowed_file(file.filename):
            filename = file.filename
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
    
    return redirect(url_for('test'))

# Обработчик для удаления изображений
@app.route('/delete', methods=['POST'])
def delete_images():
    delete_images = request.form.get('delete_images')
    if delete_images:
        delete_images = eval(delete_images)  # Преобразуем строку в список
        for filename in delete_images:
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
    
    return redirect(url_for('test'))

# Статические файлы из папки с изображениями
@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# Проверка формата файла
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ================ TEST =================


def run():
    app.run(debug=True)

if __name__ == '__main__':
    run()
