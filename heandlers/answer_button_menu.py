from aiogram import Router, F
from aiogram.types import CallbackQuery

from heandlers import menu
#from sql_mgt import sql_mgt.set_param
import sql_mgt


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)

'''
@router.callback_query(F.data.startswith("b_"))
async def callbacks_num(callback: CallbackQuery):
    print(callback.data)
    path_id = callback.data.split("_")[1]
    # !!!! надо переделать на данные которые не в кнопках
    # и добавить дату последнй загрузки туда
    # проверять её с датой последнего обновления данных, если такая была, то 
    # возвращаем в главное меню
    path = global_objects.tree_data.get_id_to_path(int(path_id))
    await menu.get_message(callback.message, path=path, replace=True)
'''

@router.callback_query(F.data.startswith("b_"))
async def callbacks_num(callback: CallbackQuery):
    #print(callback.data)
    path_id = callback.data.split("_")[1]
    path = global_objects.tree_data.get_id_to_path(int(path_id))
    await menu.get_message(callback.message, path=path, replace=True)


@router.callback_query(F.data.startswith("fix_"))
async def callbacks_fix(callback: CallbackQuery):
    #print(callback.data)
    path_id = callback.data.split("_")[1]
    path = global_objects.tree_data.get_id_to_path(int(path_id))
    current_text = callback.message.text
    current_text = '📌\n\n' + current_text
    current_keyboard = callback.message.reply_markup

    # Проверяем, что у нас есть хотя бы две кнопки для удаления предпоследней
    if current_keyboard and len(current_keyboard.inline_keyboard) > 0:
        # Удаляем предпоследнюю кнопку из первого ряда
        current_keyboard.inline_keyboard.pop(-2)
    await sql_mgt.set_param(callback.message.chat.id, 'LAST_MEDIA_LIST', '')
    await sql_mgt.set_param(callback.message.chat.id, 'DELETE_LAST_MESSAGE', '')
    await sql_mgt.set_param(callback.message.chat.id, 'LAST_MESSAGE_ID', '0')
    await global_objects.bot.edit_message_text(chat_id=callback.message.chat.id,
                                message_id=callback.message.message_id,
                                text=current_text,
                                #reply_markup=current_keyboard
                                )
    await global_objects.bot.pin_chat_message(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id
    )
    await menu.get_message(
        callback.message,
        path=path,
        replace=False
    )

@router.callback_query(F.data.startswith("site_"))
async def callbacks_site(callback: CallbackQuery):
    pass
    '''
    await menu.get_message(
        callback.message,
        path='',
        replace=False
    )
    '''