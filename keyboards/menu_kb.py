from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from keys import SPLITTER_STR
from heandlers.web_market import get_market_reply_button


global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp


def get_menu_kb(message, path, extra_rows: list[str] | None = None) -> ReplyKeyboardMarkup:
    tree_item = global_objects.tree_data.get_obj_from_path(path)
    next_layers = tree_item.next_layers
    next_buttons = list(next_layers.keys())

    keyboard: list[list[KeyboardButton]] = []
    if extra_rows:
        for row in extra_rows:
            keyboard.append([KeyboardButton(text=row)])
    for button in next_buttons:
        keyboard.append([KeyboardButton(text=button)])

    path_id = global_objects.tree_data.get_path_to_id(tree_item.path)
    if len(next_buttons) == 0:
        keyboard.append([KeyboardButton(text='Закрепить 📌')])

    if tree_item.path != SPLITTER_STR:
        previus_path = SPLITTER_STR.join(tree_item.path.split(SPLITTER_STR)[:-1])
        if not previus_path:
            previus_path = SPLITTER_STR

        keyboard.append([KeyboardButton(text='>> ↩️ НАЗАД <<')])
    
    if tree_item.path == SPLITTER_STR:
        if global_objects.settings_bot.get('site').get('site_on'):
            keyboard.append([get_market_reply_button()])

        if message.chat.id in global_objects.admin_list:
            keyboard.append([KeyboardButton(text='🔻 Админу <🔑')])
            keyboard.append([KeyboardButton(text='⭕️ 🔏 Включить админ панель <🔑')])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def tu_menu(bnt_name: str = 'НАЗАД'):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=f'>> {bnt_name} <<')]],
        resize_keyboard=True
    )
