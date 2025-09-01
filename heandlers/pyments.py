from aiogram import Router, F, Bot
from aiogram.types import Message, PreCheckoutQuery, ContentType, LabeledPrice
from aiogram.filters import Command
from heandlers import admin_answer_button, order
import datetime
import json
from keyboards.admin_kb import fill_wallet_alert_message_kb 

#from sql_mgt import sql_mgt.append_fill_wallet_line, sql_mgt.append_order_wallet_line, sql_mgt.get_wallet_data_asunc
import sql_mgt


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    admin_answer_button.init_object(global_objects)
    sql_mgt.init_object(global_objects)

    order.global_objects = global_objects
    order.sql_mgt = sql_mgt


# отправляем подтверждение, что можно произвести оплату
@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    # нужно сделать проверку, в каком статусе заказ

    # пополнение кошелька бота
    if pre_checkout_query.invoice_payload == 'FILL_WALLET':
        await process_pre_checkout_query_wallet(pre_checkout_query, bot)
        return

    #await bot.send_message(pre_checkout_query.from_user.id, str(pre_checkout_query))
    # пока просто подтверждаем, без проверки
    # нужно проверить, если заказ опласен или у него статус не ожидания оплаты, то не надо подтверждать
    pre_checkout_query.invoice_payload
    order = await sql_mgt.get_order(pre_checkout_query.invoice_payload)
    # нужно проверить, что сумма по заказу такая же как в чеке
    if order['status'] != 'NEED_PAYMENTS':
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message=f"Оплата невозможна, так как заказ находится в статусе {order['status']}! Обратитесь к менаджеру")
        return 
    
    if order['is_paid_for']:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message=f"Заказ уже оплачен!")
        return 

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    return 

    if pre_checkout_query.invoice_payload != "test_payload":
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="errors gere...")
    else:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def succesfull_payment(message: Message):
    print("succesfull_payment activate")

    '''
    if message.successful_payment.invoice_payload == 'FILL_WALLET':
        await succesfull_payment_wallet(message)
        return 
    '''
    print(message)
    msg = f"Вы оплатили заказ {message.successful_payment.invoice_payload} на сумму {message.successful_payment.total_amount // 100} руб."
    await message.answer(msg)

    email = message.successful_payment.order_info.email
    await sql_mgt.append_additional_fields(message.successful_payment.invoice_payload, {'email_sys': {'description':'Email', 'value': email}})

    #pyment_limit_per_mounth
    # вносим оплату в базу
    wallet_data = await sql_mgt.get_wallet_data_asunc()
    pyment_settings = global_objects.settings_bot.get('pyment_settings')
    pyment_limit_per_mounth = pyment_settings.get('pyment_limit_per_mounth')
    amount_procent = 0
    if pyment_limit_per_mounth < int(wallet_data.get('total_spent_month')) + message.successful_payment.total_amount/100:
        amount_procent = round(message.successful_payment.total_amount/100/100 * global_objects.settings_bot.get('procent_pyment_limit'), 2)

    await sql_mgt.append_order_wallet_line(message.from_user.id, 'PYMENT_ORDER', message.successful_payment.invoice_payload, f'Оплата заказа {message.successful_payment.invoice_payload} на сумму {message.successful_payment.total_amount/100}',
                                   message.successful_payment.total_amount/100, amount_procent)
    
    order_data = await sql_mgt.get_order(message.successful_payment.invoice_payload)
    try:
        await order.update_order_status(message.from_user.id, order_data, 'PAYMENT_SUCCESS')
    except Exception as e:
        print(f'ERROR -> succesfull_payment update_order_status {e}')
    # поставить галочку, что оплата завершена
    await sql_mgt.update_is_paid_for(order_data['no'], True)


# ============================ Работа с заказами ============================
# тестовая функция
async def buy_order(message: Message, order: dict, bot:None=None):
    pyment_settings = global_objects.settings_bot['site']['settings']
    if not bot:
        bot = global_objects.bot

    lines = order.get('lines')
    all_name_items = ', '.join([line.get('item').get('name') for line in lines])
    prices = [LabeledPrice(label=line.get('item').get('name'), amount=int(line.get('price')) * int(line.get('quantity'))) for line in lines]

    await bot.send_invoice(message.chat.id,
        title=f"Заказ - {order.get('no')}",
        description=f"Заказ: {order.get('no')}\nТовары: {all_name_items}",
        provider_token=pyment_settings.get('PAYMENTS_TOKEN'),
        currency="rub",
        photo_url=lines[0].get('item').get('media_list')[0],
        photo_width=416,
        photo_height=234,
        photo_size=416,
        is_flexible=False,
        prices=prices,
        start_parameter="payment",
        payload=order.get('no'))
    

async def buy_order_user_id(order: dict, bot:Bot=None, pyment_settings:None=None):
    
    print(pyment_settings)
    if global_objects != None:
        if not pyment_settings:
            pyment_settings = global_objects.settings_bot['site']['settings']
        if not bot:
            bot: Bot = global_objects.bot

    lines = order.get('lines')
    client_id = order.get('client_id')
    title = f"Заказ - {order.get('no')}"
    all_name_items = ', '.join([f'{line.get("name")} x{line.get("quantity")}' for line in lines])
    prices = [LabeledPrice(label=f'{line.get("name")} x{line.get("quantity")}' , amount=int(line.get('price')) * int(line.get('quantity'))) for line in lines]
    items = []
    for line in lines:
        items.append({
            "description": title,
            "quantity": "{:.2f}".format(line.get("quantity")),
            "amount": {
                "value": "{:.2f}".format(int(line.get('price'))/100),
                "currency": "RUB"
            },
            "vat_code": 1
        })

    receipt = {
        "receipt": {
            "items": items,
        }
    }
    

    item = lines[0].get('item')
    if item != None:
        item_media = item.get('media_list')[0]

    print('receipt', receipt)

    send_invoice_data = await bot.send_invoice(client_id,
        title=title,
        description=f"Заказ: {order.get('no')}\nТовары: {all_name_items}",
        provider_token=pyment_settings.get('PAYMENTS_TOKEN'),
        currency="rub",
        photo_url=item_media,
        photo_width=416,
        photo_height=234,
        photo_size=416,
        is_flexible=False,
        prices=prices,
        start_parameter="payment",
        payload=order.get('no'),
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(receipt)
    )
    
    return send_invoice_data
# ===========================================================================


# ========================= Работа с кошельком бота =========================
async def fill_willet(user_id: int, price: float, bot:None=None, pyment_settings:None=None):
    if not pyment_settings:
        pyment_settings = global_objects.settings_bot.get('pyment_settings')
    if not bot:
        bot = global_objects.bot

    title = 'Пополнение кошелька'
    description = f'Пополнение кошелька на сумму {price}'
    prices = [LabeledPrice(label=f'FILL_WALLET' , amount=int(price * 100))]

    await bot.send_invoice(user_id,
        title=title,
        description=description,
        provider_token=pyment_settings.get('PAYMENTS_TOKEN'),
        currency="rub",
        #photo_url=item_media,
        photo_width=416,
        photo_height=234,
        photo_size=416,
        is_flexible=False,
        prices=prices,
        start_parameter="payment",
        payload='FILL_WALLET')


async def process_pre_checkout_query_wallet(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await sql_mgt.append_fill_wallet_line(pre_checkout_query.from_user.id, 'PRE_FILL_WALLET', '', f'Попытка пополнить кошелёк на сумму {pre_checkout_query.total_amount / 100}', 0)
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


async def succesfull_payment_wallet(user_id, amount):
    wallet_data = await sql_mgt.append_fill_wallet_line(user_id, 'FILL_WALLET', '', f'Пополнение кошелька на сумму {amount}', amount)

    #message_data = await admin_answer_button.get_message_admin_wallet(message)
    #await message.answer(message_data[0], reply_markup=message_data[1])

# ===========================================================================