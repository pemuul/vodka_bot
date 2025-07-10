from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.enums import ParseMode

from heandlers import menu, mailing
from keyboards.callback_data_classes import SubscriptionsBot, SubscriptionsItemBot
from keyboards.subscriptions_kb import subscriptions_kb, mailing_item_kb
#from sql_mgt import sql_mgt.set_param
import sql_mgt


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)
    mailing.init_object(global_objects)


@router.callback_query(SubscriptionsBot.filter())
async def subscriptions_cmd_btn(callback: CallbackQuery, callback_data: SubscriptionsBot):
    subscription = callback_data.subscription
 
    # нужно прописать, чтобы можно было ставить галку получать или не получать попрвещения от бота
    await sql_mgt.update_user_subscription(callback.message.chat.id, subscription)

    await callback.message.edit_text("Рассылка бота:", reply_markup=subscriptions_kb(await sql_mgt.user_is_subscript(callback.message.chat.id)), parse_mode=ParseMode.HTML)


@router.callback_query(SubscriptionsItemBot.filter())
async def subscription_item_cmd_btn(callback: CallbackQuery, callback_data: SubscriptionsItemBot):
    subscription = callback_data.subscription
    path_id = callback_data.path_id
 
    # нужно прописать, чтобы можно было ставить галку получать или не получать попрвещения от бота
    await sql_mgt.update_user_subscription(callback.message.chat.id, subscription)
    
    text_message = await mailing.get_mailing_text_to_all_subscribers(path_id)
    await callback.message.edit_text(text_message, reply_markup=mailing_item_kb(subscription, path_id))