import sqlite3
import copy
import asyncio
import json
from aiogram import Bot
from sql.sql_site import get_order, get_items, get_additional_fields, get_user_orders, get_orders_lines, get_items_by_id, get_orders, get_admins, get_admin_rules, get_user, get_user_extended
from heandlers.order import update_order_status as update_order_status_async


def get_settings(path:str, file_name:str='settings.json'):
    #print(f'{path}/{file_name}')
    with open(f'{path}/{file_name}', 'r') as f:
        data = json.load(f)

    return data


def get_bot(path_text:str) -> Bot:
    settings = get_settings(path_text)
    bot = Bot(token=settings.get('TELEGRAM_BOT_TOKEN'))
    return bot


def ites_set_path_media_list(items:list, path:str) -> list:
    items = copy.deepcopy(items)
    for id_product, item in enumerate(items):
        if item != None:
            media_list_path = []
            media_list_text = item.get('media_list')
            if media_list_text:
                media_list = item['media_list'].split(',')
                for media_list_item in media_list:
                    media_list_path.append(f'/{path}/get_file/{media_list_item}')

                items[id_product]['media_list'] = media_list_path

    return items


def unique_values_from_dicts_list(dicts_list, key):
    unique_values = set()  # создаем пустое множество для хранения уникальных значений
    for d in dicts_list:  # проходим по каждому словарю в списке
        if key in d:  # проверяем, существует ли указанный ключ в текущем словаре
            unique_values.add(d[key])  # добавляем значение по ключу в множество уникальных значений
    return unique_values


def get_all_data_order(order_no: str, path:str, path_decode:str, db_file_name: str, conn=None, conn_close: bool=True):
    if not conn:
        conn = sqlite3.connect(path + '/' + db_file_name)

    user_order = [get_order(order_no, conn=conn)]
    #print(user_order)
    
    # вставляем в заказы строки
    if len(user_order) > 0:
        orders_lines = get_orders_lines(user_order, conn)
        iten_id_list = unique_values_from_dicts_list(orders_lines, 'item_id')
        items = get_items_by_id(iten_id_list, conn)
        additional_fields_list = get_additional_fields(user_order, conn)
        additional_fields = {}
        for additional_field in additional_fields_list:
            if not additional_fields.get(additional_field['sales_no']):
                additional_fields[additional_field['sales_no']] = { additional_field['field_name']: additional_field['value'] }
            else:
                additional_fields[additional_field['sales_no']][additional_field['field_name']] = additional_field['value']

        #print('items 2 -> ', items) 

        line_dict = {}
        for line_dict_item in orders_lines:
            
            line_dict_item['item'] = ites_set_path_media_list([items.get(line_dict_item.get('item_id'))], path_decode)[0]

            if not line_dict.get(line_dict_item['sales_no']):
                line_dict[line_dict_item['sales_no']] = [line_dict_item]
            else:
                line_dict[line_dict_item['sales_no']].append(line_dict_item)

        for order_id, order in enumerate(user_order):
            if additional_fields.get(order['no']):
                user_order[order_id]['additional_fields'] = additional_fields.get(order['no'])

            if line_dict.get(order['no']):
                user_order[order_id]['lines'] = line_dict.get(order['no'])

    if conn_close:
        conn.close()

    return user_order[0]



def get_all_data_orders(user_id: int, path:str, path_decode:str, db_name: str='tg_base.sqlite', conn:None=None, conn_close: bool=True):
    if not conn:
        conn = sqlite3.connect(f'{path}/{db_name}')

    if user_id == -1:
        user_orders = get_orders(conn)
    else:
        user_orders = get_user_orders(user_id, conn)
    
    # вставляем в заказы строки
    if len(user_orders) > 0:
        orders_lines = get_orders_lines(user_orders, conn)
        iten_id_list = unique_values_from_dicts_list(orders_lines, 'item_id')
        items = get_items_by_id(iten_id_list, conn)
        #print('items 2 -> ', items) 
        additional_fields_list = get_additional_fields(user_orders, conn)
        additional_fields = {}
        for additional_field in additional_fields_list:
            if not additional_fields.get(additional_field['sales_no']):
                additional_fields[additional_field['sales_no']] = { additional_field['field_name']: {'description': additional_field['field_description'], 'value': additional_field['value']} }
            else:
                additional_fields[additional_field['sales_no']][additional_field['field_name']] = {'description': additional_field['field_description'], 'value': additional_field['value']}

        line_dict = {}
        for line_dict_item in orders_lines:
            
            line_dict_item['item'] = ites_set_path_media_list([items.get(line_dict_item.get('item_id'))], path_decode)

            if not line_dict.get(line_dict_item['sales_no']):
                line_dict[line_dict_item['sales_no']] = [line_dict_item]
            else:
                line_dict[line_dict_item['sales_no']].append(line_dict_item)

        for order_id, order in enumerate(user_orders):
            if additional_fields.get(order['no']):
                user_orders[order_id]['additional_fields'] = additional_fields.get(order['no'])

            if line_dict.get(order['no']):
                user_orders[order_id]['lines'] = line_dict.get(order['no'])

    if conn_close:
        conn.close()

    return user_orders


def update_order_status(init_user_id:int, order:dict, status:str, reason:str, additional_params:dict, path_text:str, conn):
    #order = get_order(order_no, conn=conn)
    print('init_user_id -> ', init_user_id)
    #order = get_all_data_order(order_no, path_text, 'tg_base.sqlite', conn, False)
    try:
        # Попытка получить текущий event loop
        loop = asyncio.get_running_loop()
        # Если event loop запущен, создаем задачу
        additional_params['path_text'] = path_text
        loop.run_until_complete(update_order_status_async(init_user_id, order, status, reason, additional_params, bot=get_bot(path_text), sync_conn=conn))
    except RuntimeError:
        # Если event loop не запущен, создаем и запускаем новый loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        additional_params['path_text'] = path_text
        loop.run_until_complete(update_order_status_async(init_user_id, order, status, reason, additional_params, bot=get_bot(path_text), sync_conn=conn))
        loop.close()



def get_admins_all_data(conn):
    admins = get_admins(conn)
    return_admin = []
    for admin_id, admin in enumerate(admins):
        admin_rules = get_admin_rules(admin.get('user_tg_id'), conn)
        #admins[admin_id]['rule'] = [admin_rule.get('rule') for admin_rule in admin_rules]
        admin['rule'] = [admin_rule.get('rule') for admin_rule in admin_rules]
        
        admin_data = get_user(admin.get('user_tg_id'), conn)
        user_extended = get_user_extended(admin.get('user_tg_id'), conn)
        if admin_data:
            admin_data['username'] = user_extended.get('username') if user_extended != None else ''
            admin['user'] = admin_data
            return_admin.append(admin)
    return return_admin