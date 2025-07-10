import os
import sys
import asyncio
import logging

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from base64 import urlsafe_b64encode, urlsafe_b64decode

from aiogram import Router, F, Bot, Dispatcher
from aiogram.types import Message, PreCheckoutQuery, ContentType, LabeledPrice
from aiogram.filters import Command
import requests
import json

from pyment_bot_dir.sql_pyment_bot import get_pyment_data, create_payment_need_pay, get_payment_need_pay
from generate_hash import encrypt, decrypt

# Telegram bot token
path_directory = os.path.dirname(os.path.abspath(__file__))
with open(path_directory + '/pyment_bot_settings.json', 'r') as f:
    settings_bot = json.load(f)

API_TOKEN = settings_bot['BOT_TOKEN']
PAYMENT_TOKEN = settings_bot['PAYMENT_TOKEN']

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()


@router.message(Command("start"))
async def start_command(message: Message):
    #try:
    # Extract the encrypted key from the command
    atter = message.text.split(' ')
    if len(atter) == 1:
        await message.reply(f"Привет)")
        return

    encrypted_key = atter[1]
    print(encrypted_key)
    pyment_data = await get_pyment_data(encrypted_key)
    if pyment_data == None:
        await message.reply(f"Чек на оплату уже выслан или просрочен!")
        return
    
    pyment_data = json.loads(pyment_data)

    payment_need_pay_id = await create_payment_need_pay(json.dumps(pyment_data, ensure_ascii=False), encrypted_key)

    print(str(payment_need_pay_id))
    # Decrypt the key
    #return 

    # Create an invoice
    title = pyment_data.get('title')
    price = pyment_data.get('amount')

    prices = [LabeledPrice(label=title, amount=price * 100)]  # Amount in cents

    await bot.send_invoice(
        message.chat.id,
        title=title,
        description=title,
        provider_token=PAYMENT_TOKEN,
        currency='rub',
        prices=prices,
        start_parameter='payment',
        payload=str(payment_need_pay_id),
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps({
            "receipt": {
                "items": [
                    {
                        "description": title,
                        "quantity": "1.00",
                        "amount": {
                            "value": "{:.2f}".format(price),
                            "currency": "RUB"
                        },
                        "vat_code": 1
                    }
                ]
            }
        })
    )
    #except Exception as e:
    #await message.reply(f"An error occurred: {e}")

@router.pre_checkout_query()
async def pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@router.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def succesfull_payment(message: Message):
    payment_need_pay = await get_payment_need_pay(message.successful_payment.invoice_payload)
    payment_need_pay_info = json.loads(payment_need_pay[2])
    # Send a POST request to the specified URL indicating payment is made
    response = requests.post('https://designer-tg-bot.ru/set_payment', 
                             data=json.dumps(
                                {
                                    'chat_id':message.from_user.id, 
                                    'payment': 'successful', 
                                    "pument_hash": payment_need_pay[1], 
                                    "amount": message.successful_payment.total_amount // 100, 
                                    "current_directory": payment_need_pay_info.get('current_directory')
                                }, ensure_ascii=False))
    if response.status_code == 200:
        await message.reply("Оплата произведена!\nМожете возвращаться в вашего бота")
    else:
        await message.reply("Что-то пошло не так\n\nЕсли деньги не поступили, обратитесь к администратору @Pemuul")


def run_bot():
    dp.include_router(router)   

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(dp.start_polling(bot))

if __name__ == '__main__':
    run_bot()
