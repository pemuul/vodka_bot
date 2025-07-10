from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keys import SPLITTER_STR
from keyboards.callback_data_classes import SettingsBot, AdminFillWallet


def get_settings_kb():
    buttons = InlineKeyboardBuilder()

    # можно будеи расширять пункты добавляением такихже и изменением settings_name
    buttons.button(text='Рассылка', callback_data=SettingsBot(settings_name='subscriptions'))  
     
    buttons.button(text='>> СКРЫТЬ <<', callback_data=f"delete")

    buttons.adjust(1)
    return buttons.as_markup()