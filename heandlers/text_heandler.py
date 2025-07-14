from aiogram import Router,  F
from aiogram.types import Message, FSInputFile
from pathlib import Path
import json

#from sql_mgt import sql_mgt.get_param, sql_mgt.set_param
import sql_mgt
from heandlers import admin


router = Router()
global_objects = None

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

    # режим приёма вопросов
    is_get_help = await sql_mgt.get_param(message.chat.id, 'GET_HELP')
    if is_get_help == str(True):
        question_id = await sql_mgt.add_question(message.chat.id, message.text)
        await sql_mgt.add_question_message(question_id, 'user', message.text)
        await message.answer('Ваш вопрос сохранён. Мы постараемся ответить в ближайшее время.')
        await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
        return

    map_str = await sql_mgt.get_param(message.chat.id, 'CHECK_BUTTON_MAP')
    if map_str:
        try:
            btn_map = json.loads(map_str)
        except Exception:
            btn_map = {}
        rid = btn_map.get(message.text)
        if rid:
            rec = await sql_mgt.get_receipt(int(rid))
            if rec and rec.get('file_path'):
                local = Path(__file__).resolve().parent.parent / 'site_bot' / rec['file_path'].lstrip('/')
                if local.exists():
                    await message.answer_photo(FSInputFile(local), caption='Чек')
                else:
                    await message.answer('Файл не найден.')
            else:
                await message.answer('Чек не найден.')
            await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
            return

    if message.text:
        await message.answer(
            "Если вы хотите задать вопрос или что-то уточнить, перейдите в раздел \"Вопросы\""
        )

    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    # debug logging removed
