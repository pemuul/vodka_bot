from aiogram.types import Message, FSInputFile
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.enums import ParseMode
import time

#from sql_mgt import sql_mgt.add_visit, sql_mgt.insert_user, sql_mgt.get_param, sql_mgt.set_param
import sql_mgt
from keyboards.menu_kb import get_menu_kb, init_object as init_object_mkb
from keyboards.admin_kb import edit_menu_kb, init_object as init_object_akb
from keys import SPLITTER_STR


global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    sql_mgt.init_object(global_objects)

    init_object_mkb(global_objects_inp)
    init_object_akb(global_objects_inp)

async def get_message(message: Message, path=SPLITTER_STR, replace=False):
    await sql_mgt.insert_user(message)
    await sql_mgt.add_visit(message.chat.id)

    replace_last_messages = True

    # удалим сообщения, которые были введены до меню
    delete_answer_messages_str = await sql_mgt.get_param(message.chat.id, 'DELETE_ANSWER_LEATER')
    delete_answer_messages = delete_answer_messages_str.split(',')
    for delete_answer_message in delete_answer_messages:
        if delete_answer_message != '':
            try:
                await global_objects.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=int(delete_answer_message)
                )
            except Exception as e:
                print(f'Ошибка1: {e}')
    await sql_mgt.set_param(message.chat.id, 'DELETE_ANSWER_LEATER', '')

    tree_item = global_objects.tree_data.get_obj_from_path(path)

    tree_name = tree_item.path.split(SPLITTER_STR)[-1]
    #print(tree_item) 
    text_message = ''
    #if not tree_name:
    #    tree_name = 'Меню'
    if tree_name:
        text_message = f'"{tree_name}"' 
    
    tree_item_text = tree_item.text
    if tree_item_text:
        text_message += '\n\n'
        text_message += tree_item_text

    # получаем параметры данного юзера
    #user_params = await get_user_params(message.chat.id)
    last_media_message_str = await sql_mgt.get_param(message.chat.id, 'LAST_MEDIA_LIST')

    last_message_id_param = await sql_mgt.get_param(message.chat.id, 'LAST_MESSAGE_ID')
    if not last_message_id_param:
        last_message_id_param = 0

    last_message_id = int(last_message_id_param)
    delete_old_message = await sql_mgt.get_param(message.chat.id, 'DELETE_LAST_MESSAGE') == 'yes'

    # если после меню появились другие сообщения, то удаляем прошлое меню
    if hasattr(message, ('message_id')):
        if last_message_id != message.message_id:
            replace = False

            if last_message_id:
                delete_old_message = True

    # если у блока есть изображения, то собираем его и отправляем перед отправкой меню
    medias = tree_item.media
    if medias and (len(medias) > 0):
        # удаляем сообщение меню, чтобы сначала были картинки, потом меню
        if last_message_id:
            delete_old_message = True

        replace = False # создадим меню в новом сообщении 
        album_builder = MediaGroupBuilder(
            caption=tree_name
        )
        for media in medias:
            #print(media)
            album_builder.add(
                    type=media.get('type'),
                    media=media.get('file_id')
                )
            '''
            media_split = media.split('.')
            if len(media_split) > 1:
                album_builder.add(
                    type="photo",
                    media=FSInputFile(f"./images/{image}")
                )
            else:
                album_builder.add(
                    type="video",
                    media=image
                )
            '''

        last_media_message_await = await message.answer_media_group(
            media=album_builder.build(),
            disable_notification=True
        )

        last_media_message_list = [l.message_id for l in last_media_message_await]
        #await ins_up_user_params(message.chat.id, last_media_message_list=last_media_message_list)
        last_media_message_list_str = str(last_media_message_list)
        last_media_message_list_str = last_media_message_list_str[1:-1]
        await sql_mgt.set_param(message.chat.id, 'LAST_MEDIA_LIST', last_media_message_list_str)
        replace_last_messages = False # мы записали новые фото, не надо перезаписывать

    if delete_old_message:
        replace = False # создадим меню в новом сообщении 
    
    # получаем нужную клавиатуру
    on_off_admin_panel = await sql_mgt.get_param(message.chat.id, 'ADMIN_MENU')
    if on_off_admin_panel == 'on':
        reply_markup = edit_menu_kb(message, path)
    else:
        reply_markup = get_menu_kb(message, path)

    if replace:
        #await message.edit_text(text_message, reply_markup=get_menu_kb(message, path), parse_mode=ParseMode.HTML)
        await message.edit_text(text_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        last_message = await message.answer(
            text_message, 
            reply_markup=reply_markup, 
            parse_mode=ParseMode.HTML,
            disable_notification=True
        )
        last_message_id_new = last_message.message_id
        await sql_mgt.set_param(message.chat.id, 'LAST_MESSAGE_ID', str(last_message_id_new))

    # для определённых id выполняем действия
    if tree_item.item_id:
        if tree_item.item_id == 'check':
            await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(True))
    else:
        if await sql_mgt.get_param(message.chat.id, 'GET_CHECK') == str(True):
            await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(False))

    # получаем список изображений из параметров
    if last_media_message_str != '':
        #print(last_media_message_str)
        last_media_message_list_split = last_media_message_str.split(',')          
        last_media_message_list = [int(l) for l in last_media_message_list_split]
    else:
        last_media_message_list = []

    if delete_old_message:
        try:
            await global_objects.bot.delete_message(
                chat_id=message.chat.id,
                message_id=last_message_id
            )
        except Exception as e:
            print(f'Ошибка: {e}')
        await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', '')

    # удаляем сообщение с изображениями, чтобы не засорять
    if len(last_media_message_list) > 0:
        for last_media_messag_id in last_media_message_list:
            try:
                await global_objects.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=last_media_messag_id
                )
            except Exception as e:
                print(f'Ошибка: {e}')
        
        if replace_last_messages:
            await sql_mgt.set_param(message.chat.id, 'LAST_MEDIA_LIST', '')     
