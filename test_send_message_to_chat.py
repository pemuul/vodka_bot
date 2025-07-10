import asyncio
from aiogram import Bot, types

API_TOKEN = '7475296664:AAE9PwFeUkRlHvBpIkr_YCahothme8Nd_Kk'
CHANNEL_ID = '-1002270400055'
MESSAGE_ID = 60  # ID существующего сообщения, которое надо изменить

async def main():
    bot = Bot(token=API_TOKEN)
    
    # Заполнение меню для бота: добавляем команды /help и /about
    await bot.set_my_commands([
        types.BotCommand(command="start", description="🏛️ МЕНЮ 🏛️"),
        types.BotCommand(command="help", description="🩶 ПОДДЕРЖКА 🩶"),
        types.BotCommand(command="pyment", description="💳 КУПИТЬ ПОДПИСКУ  💳")
    ])
    
    # Создаем inline клавиатуру
    markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Club - начала", url="https://t.me/c/2270400055/19")],
            [types.InlineKeyboardButton(text="Модули", url="https://t.me/c/2270400055/21")],
            [types.InlineKeyboardButton(text="Эфиры", url="https://t.me/c/2270400055/48")],
            [types.InlineKeyboardButton(text="Подкасты", url="https://t.me/c/2270400055/49")],
            [types.InlineKeyboardButton(text="Игра - «ИГРОК»", url="https://t.me/c/2270400055/47")],
            [types.InlineKeyboardButton(text="Служба заботы", url="https://t.me/marianavseznaet")],
        ]
    )
    
    # Изменяем текст и кнопки у существующего сообщения
    await bot.edit_message_text(
        chat_id=CHANNEL_ID,
        message_id=MESSAGE_ID,
        text="🕹️НАВИГАЦИЯ ПО КАНАЛУ 💎",
        reply_markup=markup
    )
    
    await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
