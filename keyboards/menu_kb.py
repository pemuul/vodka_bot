from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keys import SPLITTER_STR
from keyboards.callback_data_classes import MenuCallbackFactory
from heandlers.web_market import get_market_button


global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp


def get_menu_kb(message, path) -> ReplyKeyboardMarkup:
    tree_item = global_objects.tree_data.get_obj_from_path(path)
    next_layers = tree_item.next_layers
    next_buttons = list(next_layers.keys())

    buttons = InlineKeyboardBuilder()
    for button in next_buttons:
        next_item = next_layers.get(button)
        path_id = global_objects.tree_data.get_path_to_id(next_item.path)

        buttons.button(text=button, callback_data=f"b_{path_id}")

    path_id = global_objects.tree_data.get_path_to_id(tree_item.path)
    if len(next_buttons) == 0:
        buttons.button(
            text=f'Закрепить 📌', callback_data=f"fix_{path_id}"
        )

    if tree_item.path != SPLITTER_STR:
        previus_path = SPLITTER_STR.join(tree_item.path.split(SPLITTER_STR)[:-1])
        if not previus_path:
            previus_path = SPLITTER_STR

        path_id = global_objects.tree_data.get_path_to_id(previus_path)
        buttons.button(
            text=f'>> ↩️ НАЗАД <<', callback_data=f"b_{path_id}"
        )
    
    if tree_item.path == SPLITTER_STR:
        if global_objects.settings_bot.get('site').get('site_on'):
            buttons.add(get_market_button())

        if message.chat.id in global_objects.admin_list:
            buttons.button(text=f'🔻 Админу <🔑', callback_data=f"admin_help")
            buttons.button(text='⭕️ 🔏 Включить админ панель <🔑', callback_data='admin_panel_on')

    buttons.adjust(1)
    return buttons.as_markup()


def tu_menu(bnt_name:str='НАЗАД'):
    buttons = InlineKeyboardBuilder()

    buttons.button(text=f'>> {bnt_name} <<', callback_data=f"b_{0}")

    buttons.adjust(1)
    return buttons.as_markup()