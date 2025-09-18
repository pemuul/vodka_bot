from aiogram import Router,  F
import asyncio
from aiogram.types import Message
import time
import random
import uuid
from pathlib import Path
from fns_api import get_receipt_by_qr

#from sql_mgt import sql_mgt.get_param, sql_mgt.set_param, sql_mgt.append_param_get_old
import sql_mgt
#from keys import ADMIN_ID_LIST
from heandlers import import_files, admin
from keyboards import admin_kb

import cv2
from pyzbar.pyzbar import decode, ZBarSymbol
# optional ZXing libraries may provide more robust QR reading
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


def _detect_qr(path: str) -> str | None:
    """Detect QR code, returning its payload if any."""
    img = cv2.imread(path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    decoded_objects = decode(gray, symbols=[ZBarSymbol.QRCODE])
    if decoded_objects:
        return decoded_objects[0].data.decode("utf-8")

    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(gray)
    if points is not None and data:
        return data.strip()

    return _enhanced_qr(gray)


def _check_keywords_with_ocr(path: str, keywords: list[str]) -> tuple[bool, str | None]:
    """Use OCR to search for configured keywords inside receipt image."""
    img = cv2.imread(path)
    if img is None:
        return False, "изображение не прочитано"
    if not keywords:
        return False, "ключевые слова не настроены"
    try:
        text = extract_text(img)
    except Exception:
        return False, "ошибка OCR"

    lower = text.casefold()
    vodka = any(k in lower for k in keywords)
    return vodka, None


def _enhanced_qr(gray):
    """Attempt to decode difficult QR codes by rotating, scaling,
    thresholding, and using optional ZXing-based readers."""
    detector = cv2.QRCodeDetector()
    rotate_codes = [None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE]
    for rc in rotate_codes:
        img = gray if rc is None else cv2.rotate(gray, rc)
        up = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
        for processed in (
            up,
            cv2.adaptiveThreshold(
                up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
            ),
        ):
            decoded = decode(processed, symbols=[ZBarSymbol.QRCODE])
            if decoded:
                return decoded[0].data.decode("utf-8")
            data, points, _ = detector.detectAndDecode(processed)
            if points is not None and data:
                return data.strip()
    try:
        import zxingcpp  # type: ignore
        results = zxingcpp.read_barcodes(gray)
        if results:
            return results[0].text
    except Exception:
        pass
    try:
        from pyzxing import BarCodeReader  # type: ignore
        reader = BarCodeReader()
        res = reader.decode_array(gray)
        if res and 'parsed' in res[0]:
            return res[0]['parsed']
    except Exception:
        pass
    return None


def _check_vodka_in_receipt(qr_data: str, keywords: list[str]) -> bool | None:
    """Call FNS service and search receipt items for configured products."""
    data = get_receipt_by_qr(qr_data)
    if not data:
        return None
    items = (
        data.get("items")
        or data.get("content", {}).get("items")
        or data.get("document", {}).get("receipt", {}).get("items", [])
    )
    for item in items:
        name = str(item.get("name", "")).casefold()
        if any(k in name for k in keywords):
            return True
    return False


async def process_receipt(dest: Path, chat_id: int, msg_id: int, receipt_id: int):
    loop = asyncio.get_running_loop()
    keywords_raw = await sql_mgt.get_param(0, 'product_keywords') or ''
    keywords = [k.strip().casefold() for k in keywords_raw.split(';') if k.strip()]

    qr_data = await loop.run_in_executor(
        global_objects.ocr_pool,
        _detect_qr,
        str(dest),
    )
    ocr_result: tuple[bool, str | None] | None = None
    final_status = None
    notify_messages = {
        "Подтверждён": "✅ Чек подтверждён",
        "Нет товара в чеке": "❌ Нет товара в чеке",
    }
    use_vision = False
    if qr_data:
        existing = await sql_mgt.find_receipt_by_qr(qr_data)
        if existing and existing != receipt_id:
            await sql_mgt.update_receipt_qr(receipt_id, qr_data)
            await sql_mgt.update_receipt_status(receipt_id, "Чек уже загружен")
            await global_objects.bot.send_message(
                chat_id,
                "❌ Чек уже загружен",
                reply_to_message_id=msg_id,
            )
            return
        await sql_mgt.update_receipt_qr(receipt_id, qr_data)
        try:
            vodka_found = await loop.run_in_executor(
                None, _check_vodka_in_receipt, qr_data, keywords
            )
        except Exception as exc:
            print(f"FNS check failed for receipt {receipt_id}: {exc}")
            vodka_found = None
        if vodka_found is None:
            use_vision = True
        elif vodka_found:
            final_status = "Подтверждён"
        else:
            final_status = "Нет товара в чеке"
    else:
        use_vision = True

    if use_vision:
        if ocr_result is None:
            ocr_result = await loop.run_in_executor(
                global_objects.ocr_pool,
                _check_keywords_with_ocr,
                str(dest),
                keywords,
            )
        vodka_by_vision, _ = ocr_result
        if vodka_by_vision:
            final_status = "Подтверждён"
        else:
            final_status = "Ошибка"

    if final_status is None:
        final_status = "Ошибка"

    await sql_mgt.update_receipt_status(receipt_id, final_status)

    user_message = notify_messages.get(final_status)
    if user_message:
        await global_objects.bot.send_message(
            chat_id,
            user_message,
            reply_to_message_id=msg_id,
        )


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
        except Exception:
            await message.reply('Ошибка при обработке чека. Попробуйте ещё раз.')
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
    except Exception:
        pass
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