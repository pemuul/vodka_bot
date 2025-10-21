from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from keys import SPLITTER_STR
from heandlers.web_market import get_market_reply_button


global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp


def _add_paired_rows(keyboard: list[list[KeyboardButton]], labels: list[str]) -> None:
    row: list[KeyboardButton] = []
    for label in labels:
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)


def get_menu_kb(message, path, extra_rows: list[str] | None = None) -> ReplyKeyboardMarkup:
    tree_item = global_objects.tree_data.get_obj_from_path(path)
    next_layers = tree_item.next_layers
    next_buttons = list(next_layers.keys())

    keyboard: list[list[KeyboardButton]] = []
    if extra_rows:
        _add_paired_rows(keyboard, extra_rows)
    display_buttons: list[str] = []
    has_custom_menu_label = 'В меню' in next_layers
    for button in next_buttons:
        if button == 'menu' and has_custom_menu_label:
            continue
        if button == 'menu':
            display_buttons.append('В меню')
        else:
            display_buttons.append(button)
    _add_paired_rows(keyboard, display_buttons)

    path_id = global_objects.tree_data.get_path_to_id(tree_item.path)
    # if len(next_buttons) == 0:
    #     keyboard.append([KeyboardButton(text='Закрепить 📌')])

    hide_back_button = getattr(tree_item, 'item_id', None) in {"pure_form", "cocktail"}

    if tree_item.path != SPLITTER_STR and not hide_back_button:
        previus_path = SPLITTER_STR.join(tree_item.path.split(SPLITTER_STR)[:-1])
        if not previus_path:
            previus_path = SPLITTER_STR

        keyboard.append([KeyboardButton(text='Вернуться назад ↩️')])
    
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
