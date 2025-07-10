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

    if message.text:   
        await message.answer("Пока я не умею понимать ваши сообщения, возможно у меня это получиться позже")

    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    print(message.html_text)