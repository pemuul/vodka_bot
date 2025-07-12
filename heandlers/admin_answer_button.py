from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode
import os
import sys
import json
from datetime import datetime
import requests

import sql_mgt
from heandlers import menu, admin, import_files, pyments, commands, mailing
#from sql_mgt import sql_mgt.set_param, sql_mgt.get_param, sql_mgt.delete_admin, sql_mgt.get_admins, sql_mgt.create_invite_admin_key, sql_mgt.get_wallet_data_asunc
from big_text import admin_help_text, admin_set_new_admin_help
from keyboards.callback_data_classes import AdminMenuEditCallbackFactory, AdminMoveMenuCallbackFactory, AdminCommandCallbackFactory, AdminDeleteCallbackFactory, AdminFillWallet
from keyboards import admin_kb
from keyboards.menu_kb import tu_menu
from keys import SPLITTER_STR
from heandlers.web_market import encrypt_text_by_key
from generate_hash import encrypt
#from heandlers.commands import cmd_get_log_click, cmd_get_log_visit 


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    admin_kb.init_object(global_objects)
    import_files.init_object(global_objects)
    sql_mgt.init_object(global_objects)
    commands.global_objects = global_objects
    admin.global_objects = global_objects
    mailing.init_object(global_objects)


@router.message(F.text == '🔻 Админу <🔑')
async def admin_help_msg(message: Message):
    await message.answer(
        admin_help_text,
        reply_markup=admin_kb.admin_buttons(),
        parse_mode=ParseMode.HTML,
    )
    await commands.delete_this_message(message)


@router.message(F.text.startswith('🔻 💰 Кошелёк'))
async def admin_wallet_msg(message: Message):
    msg_text, kb = await get_message_admin_wallet(message)
    await message.answer(msg_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await commands.delete_this_message(message)


@router.message(F.text == '⭕️ 🔏 Включить админ панель <🔑')
async def admin_panel_on_msg(message: Message):
    await sql_mgt.set_param(message.chat.id, 'ADMIN_MENU', 'on')
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
    await menu.get_message(message, replace=False)
    await commands.delete_this_message(message)


@router.message(F.text == '⭕️ 🔒 Отключить админ панель <🔑')
async def admin_panel_off_msg(message: Message):
    await sql_mgt.set_param(message.chat.id, 'ADMIN_MENU', 'off')
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
    await menu.get_message(message, replace=False)
    await commands.delete_this_message(message)


@router.message(F.text == '🔻 ⚙️ Управление  <🔑')
async def admin_manage_msg(message: Message):
    current_path_id = await sql_mgt.get_param(message.chat.id, 'CURRENT_PATH_ID')
    if current_path_id == '':
        current_path_id = 0
    last_message_id_param = await sql_mgt.get_param(message.chat.id, 'LAST_MESSAGE_ID')
    if not last_message_id_param:
        last_message_id_param = message.message_id
    await edit_message(message.chat.id, int(last_message_id_param), int(current_path_id))
    await commands.delete_this_message(message)


@router.message(F.text == '🔹 Число нажатий на кнопки')
async def cmd_log_click_msg(message: Message):
    await commands.cmd_get_log_click(message, 10)
    await commands.delete_this_message(message)


@router.message(F.text == '🔹 Число посещений')
async def cmd_log_visit_msg(message: Message):
    await commands.cmd_get_log_visit(message, 10)
    await commands.delete_this_message(message)


@router.message(F.text == '🔹 Добавить Админа')
async def add_admin_msg(message: Message):
    url_start = 'https://t.me/'
    me = await global_objects.bot.get_me()
    url_start += me.username
    url_start += '?start='
    url_start += await sql_mgt.create_invite_admin_key(message.chat.id)
    answerd_text = admin_set_new_admin_help + f'<a href="{url_start}">СТАТЬ АДМИНОМ</a>'
    await message.answer(answerd_text, reply_markup=tu_menu('В МЕНЮ'), parse_mode=ParseMode.HTML)
    await commands.delete_this_message(message)


@router.message(F.text == '🔻 Удалить Админа')
async def delete_admin_start_msg(message: Message):
    kb = await admin_kb.delete_admin()
    await message.answer('Удалите ненужных администраторов', reply_markup=kb, parse_mode=ParseMode.HTML)
    await commands.delete_this_message(message)


@router.message(lambda m: m.text and m.text.startswith('🔹 🗑 Удалить'))
async def delete_admin_confirm_msg(message: Message):
    parts = message.text.split()
    if len(parts) >= 3 and parts[2].isdigit():
        user_id = int(parts[2])
        add_text = ''
        if message.chat.id != user_id:
            await sql_mgt.delete_admin(user_id)
        else:
            add_text = ' (не себя)'
        kb = await admin_kb.delete_admin()
        await message.answer('Удалите ненужных администраторов' + add_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        global_objects.admin_list = [admin[0] for admin in await sql_mgt.get_admins()]
    await commands.delete_this_message(message)


@router.message(F.text == '🔹 Пополнить кошелёк')
async def fill_wallet_msg(message: Message):
    await message.answer(
        'Выберите сумму пополнения',
        reply_markup=admin_kb.fill_wallet_kb(),
        parse_mode=ParseMode.HTML,
    )
    await commands.delete_this_message(message)


@router.message(lambda m: m.text and m.text.endswith(' руб.') and m.text.split()[0].isdigit())
async def fill_amount_wallet_msg(message: Message):
    amount = int(message.text.split()[0])
    await send_payment_link(message, amount)
    await commands.delete_this_message(message)


@router.callback_query(F.data.startswith("admin_help"))
async def callback_admin_help(callback: CallbackQuery):
    await global_objects.bot.edit_message_text(admin_help_text, callback.message.chat.id, callback.message.message_id, reply_markup=admin_kb.admin_buttons(), parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("defolt_data"))
async def defolt_data(callback: CallbackQuery):
    await callback.message.answer('пока не реализованно')


@router.callback_query(F.data.startswith("return_data"))
async def return_data(callback: CallbackQuery):
    await callback.message.answer('пока не реализованно')


@router.callback_query(F.data.startswith("admin_wallet"))
async def admin_wallet(callback: CallbackQuery):
    message_data = await get_message_admin_wallet(callback.message)

    await global_objects.bot.edit_message_text(message_data[0], callback.message.chat.id, callback.message.message_id, 
                                               reply_markup=message_data[1], 
                                               parse_mode=ParseMode.HTML)


async def get_message_admin_wallet(message: Message):
    wallet_data = await sql_mgt.get_wallet_data_asunc()

    pyment_settings = global_objects.settings_bot.get('pyment_settings')
    pyment_limit_per_mounth = pyment_settings.get('pyment_limit_per_mounth')
    wallet_text = f"Ваш кошелёк\n\nБалланс: {wallet_data.get('balance', 0)} руб.\nЗа месяц было купленно на сумму: {wallet_data.get('total_spent_month', 0)} руб.\nЛимит в месяц без процента: {pyment_limit_per_mounth} руб.\n\nВсего было куплено на: {wallet_data.get('total_spent', 0)} руб.\n\nДата оплаты: {wallet_data.get('next_write_off_date', 0)}\nЕжемесячная оплата: {pyment_settings.get('monthly_payment', 0)} руб."

    return [wallet_text, admin_kb.wallet_kb()]
    

@router.callback_query(F.data.startswith("fill_wallet"))
async def fill_wallet(callback: CallbackQuery):
    message_text = 'Выберите сумму пополнения'
    await global_objects.bot.edit_message_text(message_text, callback.message.chat.id, callback.message.message_id, 
                                               reply_markup=admin_kb.fill_wallet_kb(), 
                                               parse_mode=ParseMode.HTML)


@router.callback_query(AdminFillWallet.filter())
async def fill_amount_wallet(callback: CallbackQuery, callback_data: AdminFillWallet):
    current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))

    bot_info = await global_objects.bot.get_me()
    data = {
        "current_directory": current_directory,
        "amount": callback_data.amount,
        "bot_name": bot_info.username,
        "create_datetime": str(datetime.now()),
        "title": f"Пополнение кошелька бота {bot_info.username} на сумму {callback_data.amount} руб."
    }

    response = requests.post('https://designer-tg-bot.ru/add_pyment', data=json.dumps({'pyment_data': data},  ensure_ascii=False), headers={"Content-Type": "application/json"})
    if response.status_code == 200:
        server_response = response.json()
        pyment_key = server_response.get('pyment_key')

        url_start = 'https://t.me/'
        url_start += global_objects.pyment_bot_settings['bot_name']
        url_start += '?start='
        url_start += pyment_key   
        url_start = f'<a href="{url_start}">💰ССЫЛКА НА ОПЛАТУ💰</a>'
        
        message_text = f'Приизведите оплату на сумму {callback_data.amount} руб. нашем боте: \n'
        message_text += url_start
        message_text += '\n\nСсылка действительна 1 час!'
        
        await callback.message.answer(message_text, parse_mode=ParseMode.HTML)
    else:
        await callback.message.answer('Ошибка отправки!')


async def send_payment_link(message: Message, amount: int):
    current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))

    bot_info = await global_objects.bot.get_me()
    data = {
        "current_directory": current_directory,
        "amount": amount,
        "bot_name": bot_info.username,
        "create_datetime": str(datetime.now()),
        "title": f"Пополнение кошелька бота {bot_info.username} на сумму {amount} руб.",
    }

    response = requests.post(
        'https://designer-tg-bot.ru/add_pyment',
        data=json.dumps({'pyment_data': data}, ensure_ascii=False),
        headers={"Content-Type": "application/json"},
    )
    if response.status_code == 200:
        server_response = response.json()
        pyment_key = server_response.get('pyment_key')

        url_start = 'https://t.me/' + global_objects.pyment_bot_settings['bot_name'] + '?start=' + pyment_key
        url_start = f'<a href="{url_start}">💰ССЫЛКА НА ОПЛАТУ💰</a>'

        message_text = f'Приизведите оплату на сумму {amount} руб. нашем боте: \n{url_start}\n\nСсылка действительна 1 час!'
        await message.answer(message_text, parse_mode=ParseMode.HTML)
    else:
        await message.answer('Ошибка отправки!')
    

@router.callback_query(F.data.startswith("admin_panel_"))
async def admin_panel(callback: CallbackQuery):
    admin_panel_on_off = callback.data.split("_")[2]
    await sql_mgt.set_param(callback.message.chat.id, 'ADMIN_MENU', admin_panel_on_off)

    if admin_panel_on_off == 'off':
        await menu.get_message(callback.message, replace=False)
        try:
            await global_objects.bot.delete_message(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
            )
        except Exception:
            pass
    else:
        await menu.get_message(callback.message, replace=True)


# обрабатываем нажатие кнопок редактирования элемента
@router.callback_query(AdminMenuEditCallbackFactory.filter())
async def callbacks_num_change_fab(callback: CallbackQuery, callback_data: AdminMenuEditCallbackFactory):
    # если человек не админ (отобрали права)
    if not callback.message.chat.id in global_objects.admin_list:
        await sql_mgt.set_param(callback.message.chat.id, 'ADMIN_MENU', 'off')
        
        await menu.get_message(callback.message, replace=True)
        return
    
    path = global_objects.tree_data.get_id_to_path(int(callback_data.path_id))
    tree_item = global_objects.tree_data.get_obj_from_path(path)  

    if callback_data.button == 'EDIT':
        # обнуляем параметр, чтобы не мешал 
        await edit_message(callback.message.chat.id, callback.message.message_id, callback_data.path_id)
    elif callback_data.button == 'RENAME':
        await set_params_to_edit(callback, callback_data)

        await callback.message.edit_text(f'{tree_item.key}\n\nВведите новое название!', reply_markup=admin_kb.cancel_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'NEW_TEXT':
        await set_params_to_edit(callback, callback_data)

        await callback.message.edit_text(f'{tree_item.text}\n\nВведите новый текст!', reply_markup=admin_kb.cancel_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'EDIT_MEDIA':
        await set_params_to_edit(callback, callback_data)

        await callback.message.edit_text('Отправте фото или видео, которые будут добавлены!', reply_markup=admin_kb.import_media_kb(callback_data.path_id, is_dowland=False), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'DELETE_MEDIA':
        tree_item.media = None
        await admin.replace_data()

        await sql_mgt.set_param(callback.message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

        await menu.get_message(
            callback.message,
            path=path,
            replace=False
        )
    elif callback_data.button == 'IMPORT_MEDIA':
        new_media_list_str = await sql_mgt.get_param(callback.message.chat.id, 'NEW_MEDIA_LIST')
        if new_media_list_str:
            new_media_list = new_media_list_str.split(',')
        else:
            new_media_list = []

        #new_media_list_id = [int(new_media.split('.')[0]) for new_media in new_media_list_id]
        new_media_list = sorted(new_media_list)

        new_media_list_dict = []
        if len(new_media_list) > 0:
            for new_media in new_media_list:
                new_media_split = new_media.split(' ')
                new_media_list_dict.append(
                    {
                        'type': new_media_split[1], 
                        'file_id': new_media_split[0]
                    }
                )
            print(new_media_list_dict)


        await sql_mgt.set_param(callback.message.chat.id, 'EXCEPT_MESSAGE', '')
        await sql_mgt.set_param(callback.message.chat.id, 'NEW_MEDIA_LIST', '')

        tree_item.media = new_media_list_dict
        await admin.replace_data()

        await menu.get_message(
            callback.message,
            path=path,
            replace=False
        )
    elif callback_data.button == 'DELETE':
        delete_key = path.split(SPLITTER_STR)[-1]
        tree_path_from_delete = SPLITTER_STR.join(path.split(SPLITTER_STR)[:-1])
        if not tree_path_from_delete:
            tree_path_from_delete = SPLITTER_STR

        tree_item = global_objects.tree_data.get_obj_from_path(tree_path_from_delete) 
        del tree_item.next_layers[delete_key]

        await admin.replace_data()

        await menu.get_message(
            callback.message,
            path=tree_path_from_delete,
            replace=True
        )

    elif callback_data.button == 'OTHER':
        await global_objects.bot.edit_message_text(await get_text_message(callback_data.path_id), callback.message.chat.id, callback.message.message_id, reply_markup=admin_kb.other_item_edit_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'RETURN':
        await menu.get_message(
            callback.message,
            path=path,
            replace=True
        )
    elif callback_data.button == 'ADD_ELEMENT_SELECT':  
         await callback.message.edit_text('Выбирите тип нового элемента:', reply_markup=admin_kb.select_new_element(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'ADD_REDIRECT':
        await set_params_to_edit(callback, callback_data)

        await callback.message.edit_text('Введите id элемента, куда будет ссылка', reply_markup=admin_kb.cancel_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'ADD_ELEMENT':
        await set_params_to_edit(callback, callback_data)

        await callback.message.edit_text('Введите название нового элемента', reply_markup=admin_kb.cancel_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'MOVE_ELEMENT':   
        await callback.message.edit_text(await get_text_message(callback_data.path_id), reply_markup=admin_kb.move_item_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'EDIT_ID':   
        await set_params_to_edit(callback, callback_data)

        await callback.message.edit_text("Введите id!\nЭто должно быть уникальное число!!!\n\nИли введите '-', 'это удалит id", reply_markup=admin_kb.cancel_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'ADD_ADMIN':
        #await set_params_to_edit(callback, callback_data)
        answerd_text = admin_set_new_admin_help
        url_start = 'https://t.me/'
        me = await global_objects.bot.get_me()
        url_start += me.username
        url_start += '?start='
        url_start += await sql_mgt.create_invite_admin_key(callback.message.chat.id)

        answerd_text += f'<a href="{url_start}">СТАТЬ АДМИНОМ</a>'
        await callback.message.edit_text(answerd_text, reply_markup=tu_menu('В МЕНЮ'), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'DELETE_ADMIN':
        await callback.message.edit_text('Удалите ненужных администраторов', reply_markup=await admin_kb.delete_admin(), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'ROLL_BACK_CHANGE':
        return_text = await import_files.return_last_edit()
        await callback.answer(
            text=return_text,
            show_alert=True
        )
        await edit_message(callback.message.chat.id, callback.message.message_id, callback_data.path_id)
    elif callback_data.button == 'MAILINGS':
        await global_objects.bot.edit_message_text(await get_text_message(callback_data.path_id), callback.message.chat.id, callback.message.message_id, reply_markup=admin_kb.mailing_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    elif callback_data.button == 'SEND_MAILING':
        await mailing.mailing_to_all_subscribers(int(callback_data.path_id))
        
    print(callback_data.path_id, callback_data.button)


async def set_params_to_edit(callback: CallbackQuery, callback_data: AdminMenuEditCallbackFactory):
    await sql_mgt.set_param(callback.message.chat.id, 'EXCEPT_MESSAGE', callback_data.button)
    await sql_mgt.set_param(callback.message.chat.id, 'LAST_PATH_ID', str(callback_data.path_id))
    await sql_mgt.set_param(callback.message.chat.id, 'LAST_MESSAGE_ID', str(callback.message.message_id))


async def edit_message(chat_id, message_id, path_id):
    await sql_mgt.set_param(chat_id, 'EXCEPT_MESSAGE', '')
    await sql_mgt.set_param(chat_id, 'IMPORT_MEDIA', '')
    await sql_mgt.set_param(chat_id, 'NEW_MEDIA_LIST', '')

    await global_objects.bot.edit_message_text(await get_text_message(path_id), chat_id, message_id, reply_markup=admin_kb.item_edit_kb(path_id), parse_mode=ParseMode.HTML)


async def get_text_message(path_id):
    path = global_objects.tree_data.get_id_to_path(int(path_id))
    tree_item = global_objects.tree_data.get_obj_from_path(path)

    tree_name = tree_item.path.split(SPLITTER_STR)[-1]
    if not tree_name:
        tree_name = 'Меню'
    text_message = f'"{tree_name}"' 
    
    tree_item_text = tree_item.text
    if tree_item_text:
        text_message += f'\n\n{tree_item_text}\n\n'

    next_layers = tree_item.next_layers
    next_buttons = list(next_layers.keys())

    for button in next_buttons:
        text_message += f'"{button}"\n'

    if tree_item.item_id:
        text_message += f'\n🆔: {tree_item.item_id}'

    if tree_item.redirect:
        text_message += f'\nЭто ссылка на ветку с 🆔: {tree_item.redirect}'
    
    return text_message


@router.callback_query(AdminMoveMenuCallbackFactory.filter())
async def callbacks_move_element(callback: CallbackQuery, callback_data: AdminMoveMenuCallbackFactory):
    callback_data.path_id
    path = global_objects.tree_data.get_id_to_path(int(callback_data.path_id))
    path_move = global_objects.tree_data.get_id_to_path(int(callback_data.path_id_move))
    element_name_move = path_move.split(SPLITTER_STR)[-1]
    tree_item = global_objects.tree_data.get_obj_from_path(path)  

    next_layers_list = list(tree_item.next_layers.keys())
    index_mode_element = next_layers_list.index(element_name_move)

    move_count = 0
    if callback_data.direction == 'up':
        move_count = -1
    else:
        move_count = 1

    next_layers_list[index_mode_element], next_layers_list[index_mode_element + move_count] = next_layers_list[index_mode_element + move_count], next_layers_list[index_mode_element]

    next_layers_dict = {}
    for next_layer in next_layers_list:
        next_layers_dict[next_layer] = tree_item.next_layers.get(next_layer)

    tree_item.next_layers = next_layers_dict

    await admin.replace_data()

    await callback.message.edit_text(await get_text_message(callback_data.path_id), reply_markup=admin_kb.move_item_kb(callback_data.path_id), parse_mode=ParseMode.HTML)


# обрабатываем нажатие кнопок редактирования элемента
@router.callback_query(AdminCommandCallbackFactory.filter())
async def callbacks_admin_cmd_btn(callback: CallbackQuery, callback_data: AdminCommandCallbackFactory):
    command = callback_data.command
    param = callback_data.params

    if command == 'get_log_click': 
        await commands.cmd_get_log_click(callback.message, int(param))
    elif command == 'get_log_visit': 
        await commands.cmd_get_log_visit(callback.message, int(param))


@router.callback_query(AdminDeleteCallbackFactory.filter())
async def callbacks_admin_delete_cmd_btn(callback: CallbackQuery, callback_data: AdminDeleteCallbackFactory):
    user_id = callback_data.user_id
    add_text = ''
    if callback.message.chat.id != user_id:
        await sql_mgt.delete_admin(user_id)
    else:
        add_text = ' (не себя)'

    await callback.message.edit_text('Удалите ненужных администраторов' + add_text, reply_markup=await admin_kb.delete_admin(), parse_mode=ParseMode.HTML)
    global_objects.admin_list = [admin[0] for admin in await sql_mgt.get_admins()]


@router.callback_query(F.data.startswith("delete"))
async def admin_panel(callback: CallbackQuery):
    await global_objects.bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)