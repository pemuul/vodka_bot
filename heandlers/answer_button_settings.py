from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.enums import ParseMode

from heandlers import menu
from keyboards.callback_data_classes import SettingsBot
from keyboards.subscriptions_kb import subscriptions_kb
#from sql_mgt import sql_mgt.set_param
import sql_mgt


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)

 
@router.callback_query(SettingsBot.filter())
async def settings_cmd_btn(callback: CallbackQuery, callback_data: SettingsBot):
    settings_name = callback_data.settings_name

    if settings_name == 'subscriptions':
        await callback.message.edit_text("Рассылка бота:", reply_markup=subscriptions_kb(await sql_mgt.user_is_subscript(callback.message.chat.id)), parse_mode=ParseMode.HTML)