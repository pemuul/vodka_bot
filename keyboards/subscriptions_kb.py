from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keys import SPLITTER_STR
from keyboards.callback_data_classes import SubscriptionsBot, SubscriptionsItemBot
from heandlers.web_market import get_market_button


def subscriptions_kb(is_subscript_user: bool):
    buttons = InlineKeyboardBuilder()

    if is_subscript_user:
        buttons.button(text='🔕 Отписаться', callback_data=SubscriptionsBot(subscription=False))
    else:    
        buttons.button(text='🔔 Подписаться', callback_data=SubscriptionsBot(subscription=True))
    
    
    buttons.button(text='>> СКРЫТЬ <<', callback_data=f"delete")

    buttons.adjust(1)
    return buttons.as_markup()


def mailing_item_kb(is_subscript_user: bool, item_id:int):
    buttons = InlineKeyboardBuilder()

    if is_subscript_user:
        buttons.button(text='🔕 Отписаться', callback_data=SubscriptionsItemBot(subscription=False, path_id=item_id))
    else:    
        buttons.button(text='🔔 Подписаться', callback_data=SubscriptionsItemBot(subscription=True, path_id=item_id))

    buttons.button(text='📝 Перейти', callback_data=f"b_{item_id}")    
    buttons.button(text='>> ЗАКРЫТЬ <<', callback_data=f"delete")

    buttons.adjust(1)
    return buttons.as_markup()