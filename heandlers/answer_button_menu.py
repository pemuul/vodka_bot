from aiogram import Router, F
from aiogram.types import Message

from heandlers import menu, commands
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


def _build_menu_text(path: str) -> str:
    """Return menu text for the given path."""
    tree_item = global_objects.tree_data.get_obj_from_path(path)

    tree_name = tree_item.path.split(SPLITTER_STR)[-1]
    text_message = ""
    if tree_name:
        text_message = f'"{tree_name}"'

    tree_item_text = tree_item.text
    if tree_item_text:
        text_message += "\n\n" + tree_item_text

    return text_message

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
        await commands.delete_this_message(message)
        return

    next_item = tree_item.next_layers.get(message.text)
    if next_item:
        await menu.get_message(message, path=next_item.path, replace=False)
        await commands.delete_this_message(message)
        return

    if message.text == 'Закрепить 📌':
        last_message_id_param = await sql_mgt.get_param(message.chat.id, 'LAST_MESSAGE_ID')
        if last_message_id_param:
            last_message_id = int(last_message_id_param)
            path_text = _build_menu_text(path)
            pin_text = '📌\n\n' + path_text

            await sql_mgt.set_param(message.chat.id, 'LAST_MEDIA_LIST', '')
            await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', '')
            await sql_mgt.set_param(message.chat.id, 'LAST_MESSAGE_ID', '0')

            try:
                await global_objects.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=last_message_id,
                    text=pin_text,
                )
                try:
                    await global_objects.bot.unpin_chat_message(chat_id=message.chat.id)
                except Exception as e:
                    # it is fine if there was no pinned message
                    print(f'Ошибка при откреплении: {e}')
                await global_objects.bot.pin_chat_message(
                    chat_id=message.chat.id,
                    message_id=last_message_id,
                    disable_notification=True,
                )
            except Exception as e:
                print(f'Ошибка при закреплении: {e}')

        await menu.get_message(message, path=path, replace=False)
        await commands.delete_this_message(message)

