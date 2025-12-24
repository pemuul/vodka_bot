from aiogram import Router,  F
from aiogram.types import Message
from aiogram.exceptions import SkipHandler

#from sql_mgt import sql_mgt.get_param, sql_mgt.set_param
import sql_mgt
from heandlers import admin


router = Router()
global_objects = None


async def _process_question_message(
    message: Message,
    text: str,
    media: list[dict] | None = None,
    question_type: str = 'text'
) -> None:
    question_text = text.strip() if text else ''
    if not question_text and media:
        question_text = 'Фото'
    if not question_text:
        question_text = 'Сообщение'

    question_id = await sql_mgt.add_question(message.chat.id, question_text, type_=question_type)
    await sql_mgt.add_question_message(question_id, 'user', question_text, media=media)
    await message.answer('Вопрос получен, свяжемся с вами в ближайшее время.')
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')


async def _send_default_hint(message: Message) -> None:
    await message.answer(
        "Если вы хотите что-то уточнить, перейдите в раздел «Задать вопрос»"
    )
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')


def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    admin.init_object(global_objects_inp)
    sql_mgt.init_object(global_objects_inp)


@router.message(F.text)
async def set_text(message: Message) -> None:
    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name:
        await admin.except_message(message, except_message_name)
        return

    # не перехватываем сообщения в режиме загрузки чеков
    is_get_check = await sql_mgt.get_param(message.chat.id, 'GET_CHECK')
    if is_get_check == str(True):
        raise SkipHandler

    # режим приёма вопросов
    is_get_help = await sql_mgt.get_param(message.chat.id, 'GET_HELP')
    if is_get_help == str(True):
        await _process_question_message(message, message.text, question_type='text')
        return

    if message.text:
        await _send_default_hint(message)

    # debug logging removed


@router.message(F.photo)
async def set_photo(message: Message) -> None:
    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name:
        await admin.except_message(message, except_message_name)
        return

    is_get_check = await sql_mgt.get_param(message.chat.id, 'GET_CHECK')
    if is_get_check == str(True):
        raise SkipHandler

    is_get_help = await sql_mgt.get_param(message.chat.id, 'GET_HELP')
    if is_get_help != str(True):
        raise SkipHandler

    media_payload = [{"type": "photo", "file_id": message.photo[-1].file_id}] if message.photo else None
    caption = message.caption or ''

    await _process_question_message(
        message,
        caption,
        media=media_payload,
        question_type='photo'
    )
