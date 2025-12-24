from aiogram import Router,  F
from aiogram.types import Message

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
        await message.answer('Вопрос получен, свяжемся с вами в ближайшее время.')
        await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
        return


    if message.text:
        await message.answer(
            "Если вы хотите что-то уточнить, перейдите в раздел «Задать вопрос»»"
        )

    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    # debug logging removed
