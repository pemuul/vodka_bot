
import asyncio
import os
from aiogram import Bot
import json

from site_bot.orders_mgt import get_admins_all_data


def get_bot_token(bot_directory: str):
    token = globals().get("TG_BOT") or os.getenv("TG_BOT")
    if token:
        return token
    bot_directory_settings = bot_directory + '/settings.json'
    with open(bot_directory_settings, 'r') as file:
        settings_data = json.load(file)

    return settings_data.get('TELEGRAM_BOT_TOKEN')


# Инициализация бота
async def send_message_to_user(bot_directory: str, user_id: int, message_text: str):
    api_token = get_bot_token(bot_directory)

    bot = Bot(token=api_token)
    #try:
    await bot.send_message(user_id, message_text)
        #print(f"Сообщение отправлено пользователю с ID {user_id}")
    #except Exception as e:
        #print(f"Ошибка при отправке сообщения пользователю с ID {user_id}: {e}")

# Функция, которая будет вызываться из Flask
def send_message_handler(bot_directory: str, user_id: int, message_text: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_message_to_user(bot_directory, user_id, message_text))


async def send_message_to_users(bot_directory: str, user_id_list: list, message_text: str, reply_markup = None):
    api_token = get_bot_token(bot_directory)

    params = {}
    if reply_markup:
        params['reply_markup'] = reply_markup

    bot = Bot(token=api_token)
    for user_id in user_id_list:
        try:
            await bot.send_message(user_id, message_text, **params)
        except Exception as e:
            print('ERROR send_message_to_users -> ', e)


def send_messages_handler(bot_directory: str, user_id_list: list, message_text: str, reply_markup = None):
    try:
        # Попытка получить текущий event loop
        print('user_id_list -> ', user_id_list)
        loop = asyncio.get_running_loop()
        # Если event loop запущен, создаем задачу
        loop.create_task(send_message_to_users(bot_directory, user_id_list, message_text, reply_markup))
    except RuntimeError:
        # Если event loop не запущен, создаем и запускаем новый loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_message_to_users(bot_directory, user_id_list, message_text, reply_markup))
        loop.close()
    #loop = asyncio.get_running_loop()
    #result = await loop.run_in_executor(None, sync_function)
    #asyncio.run(send_message_to_users(bot_directory, user_id_list, message_text))


# оповещаем менаджеров о создании заказа
def notify_manager_create_order(bot_directory: str, message_text: str, conn):
    # находим всех менаджеров, которых нужно оповестить
    admins = get_admins_all_data(conn)

    # отправляем каждому менаджеру сообщение 
    user_id_list = [admin.get('user').get('tg_id') for admin in admins if 'GET_INFO_MESSAGE' in admin.get('rule') ]
    send_messages_handler(bot_directory, user_id_list, message_text)

