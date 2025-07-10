from aiogram import Router, Bot
from aiogram.types import Message

import sql_mgt
from keyboards import settings_kb


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    sql_mgt.init_object(global_objects)


async def get_settings_msg(message: Message):
    return_text = 'Персональные настройки бота:\n'
    answer_message = await message.answer(return_text, reply_markup=settings_kb.get_settings_kb())
    await sql_mgt.append_param_get_old(answer_message.chat.id, 'DELETE_ANSWER_LEATER', answer_message.message_id)

    #await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')