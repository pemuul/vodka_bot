from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
import math

from keys import SPLITTER_STR
from sql_mgt import get_admins, get_wallet_data
from heandlers.web_market import (
    get_market_reply_button,
    get_market_button_setup_reply,
)
from keyboards.callback_data_classes import (
    AdminMenuEditCallbackFactory,
    AdminMoveMenuCallbackFactory,
    AdminDeleteCallbackFactory,
    AdminCommandCallbackFactory,
)


global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp


def edit_menu_kb(message, path) -> ReplyKeyboardMarkup:
    tree_item = global_objects.tree_data.get_obj_from_path(path)
    next_layers = tree_item.next_layers
    next_buttons = list(next_layers.keys())

    keyboard: list[list[KeyboardButton]] = []
    for button in next_buttons:
        keyboard.append([KeyboardButton(text=button)])

    path_id = global_objects.tree_data.get_path_to_id(tree_item.path)
    keyboard.append([KeyboardButton(text='🔻 ⚙️ Управление  <🔑')])

    if tree_item.path != SPLITTER_STR:
        keyboard.append([KeyboardButton(text='>> ↩️ НАЗАД <<')])

    if tree_item.path == SPLITTER_STR:
        if global_objects.settings_bot.get('site').get('site_on'):
            keyboard.append([get_market_reply_button()])
            keyboard.append([get_market_button_setup_reply()])

        if message.chat.id in global_objects.admin_list:
            wallet_balance = 0
            wallet_data = get_wallet_data()
            if wallet_data is not None:
                wallet_balance = wallet_data.get('balance', 0)
            keyboard.append([KeyboardButton(text='🔻 Админу <🔑')])
            keyboard.append([KeyboardButton(text=f'🔻 💰 Кошелёк: {wallet_balance} руб <🔑')])
            keyboard.append([KeyboardButton(text='⭕️ 🔒 Отключить админ панель <🔑')])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def item_edit_kb(path_id):
    buttons = InlineKeyboardBuilder()
    is_menu = path_id == 0
    path = global_objects.tree_data.get_id_to_path(int(path_id))
    tree_item = global_objects.tree_data.get_obj_from_path(path)
    is_redirect = tree_item.redirect is not None

    if not is_menu: 
        buttons.button(text='🔹 🖊 Изменить название <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='RENAME'))
    
    if not is_redirect: 
        buttons.button(text='🔹 🖊 Изменить текст <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='NEW_TEXT'))
    
    if not is_redirect: 
        buttons.button(text='🔹 🖼 Изменить фото/видео <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT_MEDIA'))
    
    if not is_menu: 
        buttons.button(text='🔹 🗑 Удалить <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='DELETE'))
    
    if not is_redirect: 
        buttons.button(text='🔻 Добавить элемент <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='ADD_ELEMENT_SELECT'))
        buttons.button(text='🔻 + Дополнительно... <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='OTHER'))
    buttons.button(text='========================', callback_data='pass')
    buttons.button(text='>> ↩️ НАЗАД <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='RETURN'))

    buttons.adjust(1)
    return buttons.as_markup()


def other_item_edit_kb(path_id):
    buttons = InlineKeyboardBuilder()
    is_menu = path_id == 0

    buttons.button(text='🔹 🔃 Изменить порядок элементов <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='MOVE_ELEMENT'))
    if not is_menu: 
        buttons.button(text='🔹 🆔 Изменить/Добавить id <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT_ID'))

    buttons.button(text='🔹 ↩️ Откатить последнее изменение <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='ROLL_BACK_CHANGE'))
    buttons.button(text='🔻 Рассылка  <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='MAILINGS'))
    buttons.button(text='========================', callback_data='pass')
    buttons.button(text='>> ↩️ НАЗАД <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT'))

    buttons.adjust(1)
    return buttons.as_markup()


def mailing_kb(path_id):
    buttons = InlineKeyboardBuilder()

    buttons.button(text='🔹 Отравить блок всем подписчикам <🔑', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='SEND_MAILING'))
    buttons.button(text='========================', callback_data='pass')
    buttons.button(text='>> ↩️ НАЗАД <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='OTHER'))

    buttons.adjust(1)
    return buttons.as_markup()


def cancel_kb(path_id):
    buttons = InlineKeyboardBuilder()

    buttons.button(text='>> ОТМЕНА <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT'))

    buttons.adjust(1)
    return buttons.as_markup()


def select_new_element(path_id):
    buttons = InlineKeyboardBuilder()

    buttons.button(text='🔹 Просто элемент', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='ADD_ELEMENT'))
    buttons.button(text='🔹 Ссылка на другой элемент', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='ADD_REDIRECT'))
    buttons.button(text='>> ОТМЕНА <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT'))

    buttons.adjust(1)
    return buttons.as_markup()


def import_media_kb(path_id, is_dowland:bool=True):
    buttons = InlineKeyboardBuilder()

    if is_dowland:
        buttons.button(text='🔹 Загрузить', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='IMPORT_MEDIA'))
    buttons.button(text='>> ОТМЕНА <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT'))
    buttons.button(text='🔹 Удалить фото/видео', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='DELETE_MEDIA'))

    button_pos = [1]
    if is_dowland:
        button_pos = [2, 1]
    buttons.adjust(*button_pos)
    return buttons.as_markup()


def move_item_kb(path_id):
    path = global_objects.tree_data.get_id_to_path(int(path_id))
    tree_item = global_objects.tree_data.get_obj_from_path(path)
    next_layers = tree_item.next_layers
    next_buttons = list(next_layers.keys())

    buttons = InlineKeyboardBuilder()

    for button_id, button in enumerate(next_buttons):
        next_item = next_layers.get(button)
        path_id_move = global_objects.tree_data.get_path_to_id(next_item.path)
        #next_item.path = ''
        
        buttons.button(text=button, callback_data="pass") 
        if button_id > 0:
            buttons.button(text='вверх ⬆️', callback_data=AdminMoveMenuCallbackFactory(path_id=path_id, path_id_move=path_id_move, direction='up')) 
        if button_id != len(next_buttons) - 1:
            buttons.button(text='вниз ⬇️', callback_data=AdminMoveMenuCallbackFactory(path_id=path_id, path_id_move=path_id_move, direction='down')) 

    buttons.button(text='========================', callback_data='pass')
    buttons.button(text='>> ↩️ НАЗАД <<', callback_data=AdminMenuEditCallbackFactory(path_id=path_id, button='EDIT'))

    adjust_list = []
    if len(next_buttons) > 1:
        adjust_list.append(2)

    if len(next_buttons) >= 3:
        adjust_list += [3 for i in range(len(next_buttons) - 2)]

    if len(next_buttons) > 1:
        adjust_list.append(2)

    buttons.adjust(*adjust_list, 1)
    return buttons.as_markup()


def admin_buttons() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text='🔹 Число нажатий на кнопки')],
        [KeyboardButton(text='🔹 Число посещений')],
        [KeyboardButton(text='🔹 Добавить Админа')],
        [KeyboardButton(text='🔻 Удалить Админа')],
        [KeyboardButton(text='>> ↩️ НАЗАД <<')],
    ]

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


async def delete_admin() -> ReplyKeyboardMarkup:
    admins = await get_admins()

    keyboard: list[list[KeyboardButton]] = []

    for admin in admins:
        keyboard.append([KeyboardButton(text=f'{admin[0]} {admin[1]}')])
        keyboard.append([KeyboardButton(text=f'🔹 🗑 Удалить {admin[0]}')])

    keyboard.append([KeyboardButton(text='>> ОТМЕНА <<')])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def wallet_kb() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text='🔹 Пополнить кошелёк')],
        [KeyboardButton(text='>> ↩️ НАЗАД <<')],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def fill_wallet_kb() -> ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for idx, amount in enumerate([60, 100, 500, 1000, 3000, 5000], start=1):
        row.append(KeyboardButton(text=f'{amount} руб.'))
        if idx % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([KeyboardButton(text='>> ↩️ НАЗАД <<')])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    

def fill_wallet_alert_message_kb(need_money: float) -> ReplyKeyboardMarkup:
    need_money = math.ceil(need_money)
    if need_money < 60:
        need_money = 60  # ограничения на оплату ТГ

    keyboard = [
        [KeyboardButton(text=f'🔹 Пополнить {need_money} руб.')],
        [KeyboardButton(text='🔹 💰 Кошелёк')],
        [KeyboardButton(text='>> СКРЫТЬ <<')],
    ]

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)