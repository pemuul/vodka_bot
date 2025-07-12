from aiogram.types.web_app_info import WebAppInfo
from aiogram.types import Message
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, FSInputFile
import base64
from cryptography.fernet import Fernet  
import os
import sys   
import random
import string

from sql.sql_site import set_param_unique_random_value 
#from sql_mgt import sql_mgt.get_items_by_id
import sql_mgt


global_objects = None
key_hash_url = 'dewqrwq12'

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp

    sql_mgt.init_object(global_objects)


async def generate_random_key(length:int):
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) for _ in range(length))


async def start(message: Message):
    await open_market_mes(message)
    

async def open_market_mes(message: Message):
    text_message = 'Вы можете заказать и олатить любой товар не выходя из ТГ'

    current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
    encode_directory_b = encrypt_text_by_key(current_directory)
    encode_directory = encode_directory_b.decode('utf-8')

    url = f'https://designer-tg-bot.ru/{encode_directory}?hash_key={await set_param_unique_random_value(message.chat.id, "hash_key")}'

    keyboard: list[list[KeyboardButton]] = []
    keyboard.append([get_market_reply_button(url=url, button_text='🎪 Магазин 🎪')])

    if message.chat.id in global_objects.admin_list:
        keyboard.append([
            get_market_button_setup_reply(
                url=f'https://designer-tg-bot.ru/{encode_directory}?lk=True',
                button_text='🛠 Магазин Настройка 🛠'
            )
        ])

    reply_kb = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

    answer_message = await message.answer(
        text_message,
        reply_markup=reply_kb,
        #parse_mode=ParseMode.HTML,
        disable_notification=True
    )

    await sql_mgt.append_param_get_old(answer_message.chat.id, 'DELETE_ANSWER_LEATER', answer_message.message_id)



''' создаём кнопку для открытия магазина '''
def get_market_button(url='', button_text='🎪 Магазин 🎪'):
    if url == '':
        current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
        encode_directory_b = encrypt_text_by_key(current_directory)
        encode_directory = encode_directory_b.decode('utf-8')
        url = f'https://designer-tg-bot.ru/{encode_directory}'

    button = InlineKeyboardButton(
        text=button_text,
        web_app=WebAppInfo(url=url)
    )

    return button


def get_market_button_setup(url='', button_text='🛠 Магазин Настройка 🛠'):
    if url == '':
        current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
        encode_directory_b = encrypt_text_by_key(current_directory)
        encode_directory = encode_directory_b.decode('utf-8')
        url = f'https://designer-tg-bot.ru/{encode_directory}?lk=True'

    button = InlineKeyboardButton(
        text=button_text,
        web_app=WebAppInfo(url=url)
    )

    return button


def get_market_reply_button(url='', button_text='🎪 Магазин 🎪'):
    """Return KeyboardButton with WebApp link for ReplyKeyboard."""
    if url == '':
        current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
        encode_directory_b = encrypt_text_by_key(current_directory)
        encode_directory = encode_directory_b.decode('utf-8')
        url = f'https://designer-tg-bot.ru/{encode_directory}'

    button = KeyboardButton(
        text=button_text,
        web_app=WebAppInfo(url=url)
    )

    return button


def get_market_button_setup_reply(url='', button_text='🛠 Магазин Настройка 🛠'):
    """Reply version of setup button."""
    if url == '':
        current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
        encode_directory_b = encrypt_text_by_key(current_directory)
        encode_directory = encode_directory_b.decode('utf-8')
        url = f'https://designer-tg-bot.ru/{encode_directory}?lk=True'

    button = KeyboardButton(
        text=button_text,
        web_app=WebAppInfo(url=url)
    )

    return button


''' шифруем текст по ключу '''
def encrypt_text_by_key(text:str, key:str=key_hash_url):
    key_bs = base64.urlsafe_b64encode(key.encode() + b'=' * (32 - len(key)))
    cipher_suite = Fernet(key_bs)
    cipher_text = cipher_suite.encrypt(text.encode())

    return cipher_text


async def send_item_message(item_id: int, message: Message):
    item_dict = await sql_mgt.get_items_by_id([item_id])
    item = item_dict.get(item_id)
    print('item', item)

    album_builder = MediaGroupBuilder(
        caption=item.get('name')
    )

    for media in item.get('media_list').split(','):
        print(media)
        album_builder.add(
            type='photo',
            media=FSInputFile('./site/market/static/'+media)
        )

    last_media_message_await = await message.answer_media_group(
        media=album_builder.build(),
        disable_notification=True
    )

    text_message = f'''"{item.get('name')}"\n'''
    text_message += '====================================\n'
    text_message += f"{item.get('description')}\n\n"
    price = int(item.get('price')) / 100
    discount =  int(item.get('discount'))
    if discount != 0:
        text_message += f'Скидка: {discount}\n'
    text_message += f'Цена: {price - (price * discount/ 100) } руб.\n'

    current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
    encode_directory_b = encrypt_text_by_key(current_directory)
    encode_directory = encode_directory_b.decode('utf-8')

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[
            get_market_reply_button(
                url=f'https://designer-tg-bot.ru/{encode_directory}?item={item_id}',
                button_text='Открыть товар'
            )
        ]],
        resize_keyboard=True
    )

    await message.answer(
        text_message,
        reply_markup=keyboard,
        #parse_mode=ParseMode.HTML,
        disable_notification=True
    )

