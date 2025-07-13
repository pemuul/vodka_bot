from aiogram import Router,  F
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
import numpy as np
from io import BytesIO
from PIL import Image
from paddleocr import PaddleOCR

# Two OCR instances for Russian and English text
ocr_ru = PaddleOCR(use_angle_cls=True, lang="ru")
ocr_en = PaddleOCR(use_angle_cls=True, lang="en")


def extract_text(opencv_image):
    """Recognize Russian and English text using PaddleOCR."""
    texts = []
    # PaddleOCR expects RGB images
    rgb_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB)
    for ocr in (ocr_ru, ocr_en):
        try:
            # `cls` parameter is not supported by all PaddleOCR versions
            results = ocr.ocr(rgb_image)
            for line in results:
                if len(line) >= 2:
                    texts.append(line[1][0])
        except Exception as e:
            print(f"OCR error: {e}")
    return " ".join(texts)



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


@router.message(F.photo)
async def set_photo(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    is_get_check = await sql_mgt.get_param(message.chat.id, 'GET_CHECK')
    if is_get_check == str(True):
        photo = message.photo[-1]
        try:
            photo_file = await global_objects.bot.download(photo.file_id)
            image = Image.open(BytesIO(photo_file.getvalue())).convert('RGB')
            opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            fname = f"{uuid.uuid4().hex}.jpg"
            dest = UPLOAD_DIR_CHECKS / fname
            with dest.open("wb") as f:
                f.write(photo_file.getvalue())

            decoded_objects = decode(opencv_image)
            status = 'Подтвержден'
            if decoded_objects:
                for obj in decoded_objects:
                    qr_data = obj.data.decode('utf-8')
                    await message.reply(f'QR-код найден! Значение: {qr_data}')
                    break
            else:
                text = ''
                try:
                    text = extract_text(opencv_image)
                except Exception:
                    text = ''
                lower = text.lower()
                if 'водк' in lower and ('фин' in lower or 'fin' in lower):
                    await message.reply('Чек принят!')
                else:
                    status = 'Не подтвержден'
                    await message.reply('Пожалуйста, пришлите чек ещё раз, на фото не видно нужных данных.')

            await sql_mgt.add_receipt(str(dest), message.chat.id, status)
            await sql_mgt.set_param(message.chat.id, 'GET_CHECK', str(False))
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
        await global_objects.bot.edit_message_text(message_text, message.chat.id, int(last_message_id), reply_markup=admin_kb.import_media_kb(last_path_id))
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