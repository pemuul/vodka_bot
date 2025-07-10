import datetime
import json
import sqlite3

from sql import sql_site
from pyment_bot_dir import sql_pyment_bot
from site_bot.send_bot_message import send_messages_handler
from keyboards.admin_kb import fill_wallet_alert_message_kb 


def monthly_payment_with_conn(current_directory):
    db_file = current_directory + '/tg_base.sqlite'
    conn = sqlite3.connect(db_file)
    try:
        monthly_payment(current_directory, conn)

    except Exception as e:
        print('ERROR -> ', e)

    finally:
        conn.close()

def monthly_payment(current_directory, conn):
    wallet_data = sql_pyment_bot.get_wallet_data(conn)
    #print("wallet_data['next_write_off_date'] -> ", datetime.datetime.strptime(wallet_data['next_write_off_date'], "%Y-%m-%d"), datetime.datetime.now())
    pay_date = datetime.datetime.strptime(wallet_data['next_write_off_date'], "%Y-%m-%d")

    bot_directory_settings = current_directory + '/settings.json'
    with open(bot_directory_settings, 'r') as file:
        settings_data = json.load(file)

    monthly_payment = settings_data['pyment_settings']['monthly_payment']

    if (datetime.datetime.now() < pay_date):
        return
    
    admins_dict = sql_site.get_admins_id(conn)

    admin_list = [admin[0] for admin in admins_dict]

    if datetime.datetime.now() >= pay_date:
        if wallet_data['balance'] - monthly_payment < 0:
            # если сегодня оплата или позже и денег нехватает, то оповещаем 
            message_text = f"🚧🚧🚧\nНа счёте бота закончились средства\n🚧🚧🚧\n\nНа баллансе нехватает {(wallet_data['balance'] - monthly_payment) * -1} рублей.\n\nПополните счёт иначе, бот будет заблокирован!"
            #for admon in admin_list:
            send_messages_handler(current_directory, admin_list, message_text, reply_markup=fill_wallet_alert_message_kb((wallet_data['balance'] - monthly_payment) * -1))
        else:
            # если деньги есть и сегодня или уже прошёл день оплаты, то мы снимем деньги и + месяц до следущей даты оплаты
            wallet_data_new = sql_pyment_bot.payment_bot(settings_data['pyment_settings']['monthly_payment'], conn=conn)
            message_text = f"Бот оплачен!\n\nСледущее списание будет: {wallet_data_new['next_write_off_date']}"
            #for admon in global_objects.admin_list:
            #    await global_objects.bot.send_message(admon, message_text)
            
            send_messages_handler(current_directory, admin_list, message_text)

    elif (pay_date <= datetime.datetime.now() + datetime.timedelta(days=5)) and (wallet_data['balance'] - monthly_payment < 0):
        # если за 5 дней до оплаты денег нехватает, то оповещаем менаджеров
        #admins_dict = await sql_mgt.get_admins_id()
        message_text = f"На счёте бота закончились средства!\n\nЧерез {pay_date - datetime.datetime.now()} дней будет списание.\n\nНа баллансе нехватает {(wallet_data['balance'] - monthly_payment) * -1} рублей"
        #for admon in admin_list:
            #await global_objects.bot.send_message(admon, message_text, reply_markup=fill_wallet_alert_message_kb((wallet_data['balance'] - monthly_payment) * -1))
        send_messages_handler(current_directory, admin_list, message_text, reply_markup=fill_wallet_alert_message_kb((wallet_data['balance'] - monthly_payment) * -1))
    