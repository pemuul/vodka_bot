import os
import shutil
import glob
import heapq

from aiogram import Router
from aiogram.types import Message
from aiogram.enums import ParseMode

import sql_mgt
#from sql_mgt import sql_mgt.get_param, sql_mgt.add_admin
from heandlers import admin_answer_button, menu
from heandlers.import_files import get_next_filename
from keys import MAIN_JSON_FILE, SPLITTER_STR
from json_data_mgt import TreeObject
from keyboards import admin_kb
from keyboards.menu_kb import tu_menu


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    admin_answer_button.init_object(global_objects_inp)
    menu.init_object(global_objects_inp)
    admin_kb.init_object(global_objects_inp)
    sql_mgt.init_object(global_objects_inp)


async def except_message(message: Message, except_message_name: str):
    last_path_id = await sql_mgt.get_param(message.chat.id, 'LAST_PATH_ID')
    last_message_id = await sql_mgt.get_param(message.chat.id, 'LAST_MESSAGE_ID')

    path = global_objects.tree_data.get_id_to_path(int(last_path_id))
    tree_item = global_objects.tree_data.get_obj_from_path(path)  

    error_text = None

    if except_message_name == 'RENAME':
        if SPLITTER_STR in message.html_text:
            #await message.edit_text('Введите новое название!\nНельзя вводить использовать / !', reply_markup=message.reply_markup)
            await global_objects.bot.edit_message_text(
                text=f'{tree_item.key}\n\nВведите новое название!\nНельзя в тексте использовать {SPLITTER_STR} !',
                chat_id=message.chat.id,
                message_id=int(last_message_id),
                reply_markup=admin_kb.cancel_kb(last_path_id),
            )
            return

        if tree_item.key != message.html_text:
            tree_item.key = message.html_text
            await replace_data()

    elif except_message_name == 'NEW_TEXT':
        if tree_item.text != message.html_text:
            tree_item.text = message.html_text
            await replace_data()

    elif except_message_name == 'EDIT_ID':
        if tree_item.item_id != message.html_text:
            tree_item.item_id = message.html_text

            if message.html_text == '-':
                tree_item.item_id = None

            await replace_data()
    elif except_message_name == 'DELETE':
        pass
    elif except_message_name == 'ADD_ELEMENT':
        tree_data = TreeObject(message.html_text, {})
        tree_data.text = 'заглушка'
        tree_item.next_layers[message.html_text] = tree_data
        await replace_data()
    elif except_message_name == 'ADD_REDIRECT':
        #tree_data = TreeObject(message.html_text, {})
        set_id = message.html_text
        redirect_path = global_objects.tree_data.id_dict.get(set_id)
        if not redirect_path:
            print('не нашли, надо будет пользователю дать ответ')
            return
        tree_redirect = global_objects.tree_data.get_obj_from_path(redirect_path)
        tree_data = TreeObject(message.html_text, {})
        tree_data.redirect = set_id

        new_redirect_name = tree_redirect.key
        while tree_item.next_layers.get(new_redirect_name):
            name_use = tree_item.next_layers.get(new_redirect_name)
            new_redirect_name = name_use.key + '1'
            
        tree_data.key = new_redirect_name
        tree_item.next_layers[new_redirect_name] = tree_data

        await replace_data()
    elif except_message_name == 'ADD_ADMIN':
        try:
            new_admin_id = int(message.html_text)
        except:
            await global_objects.bot.edit_message_text(
                text='Вам нужно ввести только число!',
                chat_id=message.chat.id,
                message_id=last_message_id,
                reply_markup=tu_menu('ОТМЕНА'),
                parse_mode=ParseMode.HTML,
            )
            await delete_message(message.chat.id, message.message_id)
            return 

        await sql_mgt.add_admin(new_admin_id, message.chat.id)
        global_objects.admin_list.append(new_admin_id)

        await global_objects.bot.edit_message_text(
            text='Администратор добавлен!',
            chat_id=message.chat.id,
            message_id=last_message_id,
            reply_markup=tu_menu('В МЕНЮ'),
            parse_mode=ParseMode.HTML,
        )
        await delete_message(message.chat.id, message.message_id)
        return

    await admin_answer_button.edit_message(message.chat.id, last_message_id, last_path_id)

    await delete_message(message.chat.id, message.message_id)


async def replace_data():
    tree_item = global_objects.tree_data.get_obj_from_path(SPLITTER_STR)
    file_name = get_next_filename() + '.json'
    tree_item.save_to_file('./load_files/' + file_name)
    global_objects.tree_data.check_json_file_valid('./load_files/' + file_name)

    os.remove(MAIN_JSON_FILE)
    shutil.copy('./load_files/' + file_name, MAIN_JSON_FILE)
    await delete_old_file('./load_files/')
    
    global_objects.tree_data.create_obj_data_from_json(MAIN_JSON_FILE)


async def delete_old_file(directory_path:str, pattern:str = 'data_tree_*', to_leave_count:int = 20):
    # Определите шаблон файлов для поиска
    file_pattern = os.path.join(directory_path, pattern)

    # Найдите все файлы, соответствующие шаблону
    files = glob.glob(file_pattern)

    # Если файлов больше 20, оставьте только последние 20
    if len(files) > to_leave_count:
        # Определите функцию, чтобы получить время последнего изменения файла
        get_file_mtime = lambda f: os.path.getmtime(f)

        # Получите 20 последних файлов с использованием heapq
        latest_files = heapq.nlargest(to_leave_count, files, key=get_file_mtime)

        # Удалите оставшиеся файлы
        for file in files:
            if file not in latest_files:
                os.remove(file)


async def delete_message(chat_id:int, message_id:int):
    await global_objects.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )

