from aiogram import Router,  F
import asyncio
from aiogram.types import Message
import time
import random
import uuid
from pathlib import Path

#from sql_mgt import sql_mgt.get_param, sql_mgt.set_param, sql_mgt.append_param_get_old
import sql_mgt
#from keys import ADMIN_ID_LIST
from heandlers import import_files, admin
from keyboards import admin_kb

import cv2
from pyzbar.pyzbar import decode
# OCR helper based on Tesseract with Russian and English models
from ocr import extract_text



router = Router()
global_objects = None
UPLOAD_DIR_CHECKS = Path(__file__).resolve().parent.parent / "site_bot" / "static" / "uploads"
UPLOAD_DIR_CHECKS.mkdir(parents=True, exist_ok=True)

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    import_files.init_object(global_objects_inp)
    admin.init_object(global_objects_inp)
    sql_mgt.init_object(global_objects_inp)


def _analyze_check(path: str):
    """Run heavy OCR logic in a separate process."""
    img = cv2.imread(path)
    if img is None:
        return None, False

    decoded_objects = decode(img)
    qr_data = decoded_objects[0].data.decode("utf-8") if decoded_objects else None

    text = ""
    if qr_data is None:
        try:
            text = extract_text(img)
        except Exception:
            text = ""
    lower = text.lower()
    vodka = "водк" in lower and ("фин" in lower or "fin" in lower)
    return qr_data, vodka


async def process_receipt(dest: Path, chat_id: int, msg_id: int, receipt_id: int):
    loop = asyncio.get_running_loop()
    qr_data, vodka = await loop.run_in_executor(global_objects.ocr_pool, _analyze_check, str(dest))
    if qr_data:
        await global_objects.bot.send_message(chat_id, f"QR-код найден! Значение: {qr_data}")
        status = "Распознан"
    elif vodka:
        await global_objects.bot.send_message(chat_id, "Чек принят!", reply_to_message_id=msg_id)
        status = "Распознан"
    else:
        status = "Не распознан"

    await sql_mgt.update_receipt_status(receipt_id, status)


@router.message(F.photo)
async def set_photo(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    is_get_check = await sql_mgt.get_param(message.chat.id, 'GET_CHECK')
    if is_get_check == str(True):
        if await sql_mgt.is_user_blocked(message.chat.id):
            await message.reply('Вы заблокированы и не можете участвовать в розыгрыше')
            return
        photo = message.photo[-1]
        try:
            photo_file = await global_objects.bot.download(photo.file_id)
            fname = f"{uuid.uuid4().hex}.jpg"
            dest = UPLOAD_DIR_CHECKS / fname
            with dest.open("wb") as f:
                f.write(photo_file.getvalue())

            web_path = f"/static/uploads/{fname}"
            draw_id = await sql_mgt.get_active_draw_id()
            receipt_id = await sql_mgt.add_receipt(
                web_path,
                message.chat.id,
                "В авто обработке",
                message_id=message.message_id,
                draw_id=draw_id,
            )
            await message.reply('Чек получен, идёт обработка...')
            asyncio.create_task(process_receipt(dest, message.chat.id, message.message_id, receipt_id))
            return
        except Exception as e:
            await message.reply('Ошибка при обработке чека. Попробуйте ещё раз.')
            print(f'Ошибка при обработке фото: {e}')
            return
    
    if not message.chat.id in global_objects.admin_list:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return
    
    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name == 'EDIT_MEDIA':
        await add_admin_media(message)
        return

    await import_files.set_new_image(message)


async def add_admin_media(message: Message, type_file:str = 'image'):
    if type_file == 'image':
        #image_name = await import_files.dowland_image(message)
        media_name = message.photo[-1].file_id + ' photo'
    elif type_file == 'video':
        #image_name = await import_files.dowland_video(message)
        media_name = message.video.file_id + ' video'
    elif type_file == 'video_file':
        media_name = message.document.file_id + ' video'

    last_path_id = await sql_mgt.get_param(message.chat.id, 'LAST_PATH_ID')
    last_message_id = await sql_mgt.get_param(message.chat.id, 'LAST_MESSAGE_ID')

    # чтобы у нас число сообщений отображалось корректно и они не попадали все разом
    delay = random.uniform(0.2, 1)
    time.sleep(delay)

    new_media_list_str = await sql_mgt.append_param_get_old(message.chat.id, 'NEW_MEDIA_LIST', media_name)

    if new_media_list_str:
        new_media_list = new_media_list_str.split(',')
    else:
        new_media_list = []

    message_text = f'Отправте фото или видео, которые будут добавлены!\nЗагружено медиа: {len(new_media_list)}'

    try:
        await global_objects.bot.edit_message_text(
            text=message_text,
            chat_id=message.chat.id,
            message_id=int(last_message_id),
            reply_markup=admin_kb.import_media_kb(last_path_id),
        )
    except Exception as e:
        print(e)
    #await callback.message.edit_text(f'Отправте фото, которые будут добавлены!\nЗагружено фото: {}', reply_markup=admin_kb.import_media_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    

@router.message(F.video)
async def set_video(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    if not message.chat.id in global_objects.admin_list:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return   

    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name == 'EDIT_MEDIA':
        await add_admin_media(message, type_file='video')
        return

    await global_objects.bot.send_message(message.from_user.id, f"У видео id:\n{message.video.file_id}", reply_to_message_id=message.message_id)



async def set_video_file(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    if not message.chat.id in global_objects.admin_list:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return   

    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name == 'EDIT_MEDIA':
        await add_admin_media(message, type_file='video_file')
        return

    await global_objects.bot.send_message(message.from_user.id, f"У видео id:\n{message.document.file_id}", reply_to_message_id=message.message_id)