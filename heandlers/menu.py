from aiogram.types import Message, FSInputFile
from pathlib import Path
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.enums import ParseMode
import time
import json

#from sql_mgt import sql_mgt.add_visit, sql_mgt.insert_user, sql_mgt.get_param, sql_mgt.set_param
import sql_mgt
from keyboards.menu_kb import get_menu_kb, init_object as init_object_mkb
from keyboards.admin_kb import edit_menu_kb, init_object as init_object_akb
from keys import SPLITTER_STR, DELETE_MESSAGES, SHOW_SECTION_NAME


STATUS_ICON_MAP = {
    "подтверждён": "✅",
    "подтвержден": "✅",
    "распознан": "✅",
    "ошибка": "⏳",
    "в авто обработке": "⏳",
    "чек уже загружен": "❌",
    "нет товара в чеке": "❌",
}
DEFAULT_STATUS_ICON = "⏳"


global_objects = None


def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    sql_mgt.init_object(global_objects)

    init_object_mkb(global_objects_inp)
    init_object_akb(global_objects_inp)


def is_root_menu(tree_item) -> bool:
    """Return True if the tree item represents the root menu."""

    if not tree_item:
        return False

    if tree_item.path == SPLITTER_STR:
        return True

    redirect_id = getattr(tree_item, "redirect", None)
    if redirect_id is None or global_objects is None:
        return False

    redirect_path = global_objects.tree_data.id_dict.get(redirect_id)
    return redirect_path == SPLITTER_STR

async def get_message(message: Message, path=SPLITTER_STR, replace=False):
    await sql_mgt.insert_user(message)
    await sql_mgt.add_visit(message.chat.id)

    replace_last_messages = True

    # удалим сообщения, которые были введены до меню
    delete_answer_messages_str = await sql_mgt.get_param(message.chat.id, 'DELETE_ANSWER_LEATER')
    delete_answer_messages = delete_answer_messages_str.split(',')
    if DELETE_MESSAGES:
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
    if is_root_menu(tree_item) and tree_item.path != SPLITTER_STR:
        path = SPLITTER_STR
        tree_item = global_objects.tree_data.get_obj_from_path(path)
    path_id_current = global_objects.tree_data.get_path_to_id(tree_item.path)
    await sql_mgt.set_param(message.chat.id, 'CURRENT_PATH_ID', str(path_id_current))

    tree_name = tree_item.path.split(SPLITTER_STR)[-1]
    #print(tree_item)
    text_message = ''
    #if not tree_name:
    #    tree_name = 'Меню'
    if SHOW_SECTION_NAME and tree_name:
        text_message = f'"{tree_name}"'
    
    tree_item_text = tree_item.text
    if tree_item.path == SPLITTER_STR and await sql_mgt.is_user_blocked(message.chat.id):
        blocked_note = (
            "Вы заблокированы!\n"
            "Для разблокировки уточните причину на вкладке Вопрос.\n\n"
        )
        text_message = blocked_note + text_message
    if tree_item_text:
        if text_message:
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
        album_builder = MediaGroupBuilder()
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

    if delete_old_message and DELETE_MESSAGES:
        replace = False # создадим меню в новом сообщении
    
    # получаем нужную клавиатуру
    on_off_admin_panel = await sql_mgt.get_param(message.chat.id, 'ADMIN_MENU')
    extra_buttons = None
    if tree_item.item_id == 'check':
        active_draw_id = await sql_mgt.get_active_draw_id()
        receipts = []
        await sql_mgt.set_param(message.chat.id, 'CHECK_BUTTON_MAP', '')
        if active_draw_id is None:
            text_message = (
                "📫-Сейчас акция не проводится\n"
                "Следите за рассылками в чат-боте – мы обязательно сообщим о старте новых промоакций!"
            )
        else:
            receipts = await sql_mgt.get_user_receipts(
                message.chat.id, limit=None, draw_id=active_draw_id
            )
            if receipts:
                me = await global_objects.bot.get_me()
                text_message += "\n\nВаши чеки:\n"
                for r in receipts:
                    ts = r.get("create_dt")
                    if ts:
                        if hasattr(ts, "isoformat"):
                            ts = ts.isoformat()
                        name = ts.replace("T", " ")[:16]
                    else:
                        name = f"Чек #{r['id']}"
                    link = f"https://t.me/{me.username}?start=receipt_{r['id']}"
                    status = (r.get('status') or '').lower()
                    mark = STATUS_ICON_MAP.get(status, DEFAULT_STATUS_ICON)
                    text_message += f'<a href="{link}">{name}</a> {mark}\n'
    else:
        await sql_mgt.set_param(message.chat.id, 'CHECK_BUTTON_MAP', '')

    if on_off_admin_panel == 'on':
        inline_kb = edit_menu_kb(message, path)
        reply_kb = get_menu_kb(message, path, extra_buttons)
    else:
        reply_kb = get_menu_kb(message, path, extra_buttons)
        inline_kb = None

    if on_off_admin_panel == 'on':
        # update reply keyboard separately
        tmp_msg = await message.answer(
            "\u2063", reply_markup=reply_kb, disable_notification=True
        )
        try:
            await tmp_msg.delete()
        except Exception as error:
            print(f"Не удалось удалить служебное сообщение меню: {error}")

        if replace:
            await message.edit_text(
                text_message,
                reply_markup=inline_kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            last_message = await message.answer(
                text_message,
                reply_markup=inline_kb,
                parse_mode=ParseMode.HTML,
                disable_notification=True,
                disable_web_page_preview=True,
            )
            last_message_id_new = last_message.message_id
            await sql_mgt.set_param(message.chat.id, 'LAST_MESSAGE_ID', str(last_message_id_new))
            # send rules pdf if available
            if tree_item.item_id == 'rule':
                pdf_path = await sql_mgt.get_param(0, 'RULE_PDF')
                if pdf_path:
                    local = Path(__file__).resolve().parent.parent / 'site_bot' / pdf_path.lstrip('/')
                    if local.exists():
                        ext = local.suffix
                        filename = f"Правила акции{ext}" if ext else "Правила акции"
                        doc = await message.answer_document(
                            FSInputFile(local, filename=filename),
                            caption="Правила акции",
                        )
                        await sql_mgt.append_param_get_old(
                            message.chat.id, 'LAST_MEDIA_LIST', str(doc.message_id)
                        )
                        replace_last_messages = False
    else:
        if replace:
            await message.edit_text(
                text_message,
                reply_markup=reply_kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            last_message = await message.answer(
                text_message,
                reply_markup=reply_kb,
                parse_mode=ParseMode.HTML,
                disable_notification=True,
                disable_web_page_preview=True,
            )
            last_message_id_new = last_message.message_id
            await sql_mgt.set_param(message.chat.id, 'LAST_MESSAGE_ID', str(last_message_id_new))
            if tree_item.item_id == 'rule':
                pdf_path = await sql_mgt.get_param(0, 'RULE_PDF')
                if pdf_path:
                    local = Path(__file__).resolve().parent.parent / 'site_bot' / pdf_path.lstrip('/')
                    if local.exists():
                        ext = local.suffix
                        filename = f"Правила акции{ext}" if ext else "Правила акции"
                        doc = await message.answer_document(
                            FSInputFile(local, filename=filename),
                            caption="Правила акции",
                        )
                        await sql_mgt.append_param_get_old(
                            message.chat.id, 'LAST_MEDIA_LIST', str(doc.message_id)
                        )
                        replace_last_messages = False

    # для определённых id выполняем действия
    is_check_section = tree_item.item_id == 'check'
    is_help_section = tree_item.item_id == 'help'

    if tree_item.item_id:
        if is_check_section:
            if await sql_mgt.is_user_blocked(message.chat.id):
                await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(False))
                await message.answer(
                    "Вы заблокированы и не можете участвовать в розыгрыше"
                )
            else:
                active_draw_id = await sql_mgt.get_active_draw_id()
                if active_draw_id is None:
                    await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(False))
                else:
                    await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(True))
        elif is_help_section:
            await sql_mgt.set_param(message.chat.id, 'GET_HELP', str(True))

    if not is_check_section and await sql_mgt.get_param(message.chat.id, 'GET_CHECK') == str(True):
        await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(False))
    if not is_help_section and await sql_mgt.get_param(message.chat.id, 'GET_HELP') == str(True):
        await sql_mgt.set_param(message.chat.id, 'GET_HELP', str(False))

    # получаем список изображений из параметров
    if last_media_message_str != '':
        #print(last_media_message_str)
        last_media_message_list_split = last_media_message_str.split(',')          
        last_media_message_list = [int(l) for l in last_media_message_list_split]
    else:
        last_media_message_list = []

    if delete_old_message and DELETE_MESSAGES:
        try:
            await global_objects.bot.delete_message(
                chat_id=message.chat.id,
                message_id=last_message_id
            )
        except Exception as e:
            print(f'Ошибка: {e}')
        await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', '')

    # удаляем сообщение с изображениями, чтобы не засорять
    if DELETE_MESSAGES and len(last_media_message_list) > 0:
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
