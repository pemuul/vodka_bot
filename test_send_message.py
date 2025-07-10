import asyncio
from aiogram import Bot


API_TOKEN = '6853605701:AAGjBUGFgLgHgAafGdqG-gb3KCiXytt8BUI'

# Инициализация бота
bot = Bot(token=API_TOKEN)
async def send_message_to_user(user_id: int, message_text: str):
    try:
        await bot.send_message(user_id, message_text)
        print(f"Сообщение отправлено пользователю с ID {user_id}")
    except Exception as e:
        print(f"Ошибка при отправке сообщения пользователю с ID {user_id}: {e}")

# Функция, которая будет вызываться из Flask
def send_message_handler(user_id: int, message_text: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_message_to_user(user_id, message_text))

send_message_handler(1087624586, 'eeeeeee')