from aiogram import Router, F
from aiogram.types import Message

from heandlers import menu
#from sql_mgt import sql_mgt.set_param
import sql_mgt
from keys import SPLITTER_STR


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)

@router.message(F.text)
async def menu_text_handler(message: Message):
    """Handle menu navigation using ReplyKeyboard buttons."""
    current_path_id = await sql_mgt.get_param(message.chat.id, 'CURRENT_PATH_ID')
    if current_path_id == '':
        current_path_id = 0
    path = global_objects.tree_data.get_id_to_path(int(current_path_id))
    tree_item = global_objects.tree_data.get_obj_from_path(path)

    # обработка кнопки Назад
    if message.text == '>> ↩️ НАЗАД <<':
        previus_path = SPLITTER_STR.join(tree_item.path.split(SPLITTER_STR)[:-1])
        if not previus_path:
            previus_path = SPLITTER_STR
        await menu.get_message(message, path=previus_path, replace=False)
        return

    next_item = tree_item.next_layers.get(message.text)
    if next_item:
        await menu.get_message(message, path=next_item.path, replace=False)

