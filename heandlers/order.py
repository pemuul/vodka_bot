from aiogram import Router, Bot

#from sql_mgt import sql_mgt.update_order_status_sql, sql_mgt.get_admins_by_rule, sql_mgt.add_cancel_order, sql_mgt.get_cancel_orders, sql_mgt.get_order
import sql_mgt
import aiosqlite
from heandlers import pyments
from keys import DELETE_MESSAGES
from datetime import datetime, timedelta


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    pyments.init_object(global_objects_inp)
    sql_mgt.init_object(global_objects_inp)

    global_objects = global_objects_inp
    

async def update_order_status(init_user_id:int, order_data:dict, status:str, reason:str='', additional_params:dict={}, bot:Bot=None, conn=None, sync_conn=None):
    # !!! если заказ только создан, то мы не можем нормально из воздухаполучить conn, он может быть неактуальным
    
    if bot == None:
        bot = global_objects.bot

    if sql_mgt.db_name == None:
        sql_mgt.db_name = f"{additional_params['path_text']}/{sql_mgt.DB_NAME}"


    if order_data['status'] == 'CANCEL':
        return
    
    print(order_data)

    if status == 'CANCEL':
        #снимаем резерв с товаров 
        lines = order_data['lines']
        for line in lines:
            if line.get('item') != None:
                await sql_mgt.subtract_amount_item(line['item']['id'], line['reserv'] * -1)

        if reason == '':
            reason = 'Отменён менеджером'
        # отправляем пользователю сообщение, что заказ отменён
        try:
            await bot.send_message(order_data['client_id'], f"Ваш заказ {order_data['no']} был отменён.\n\nПо причине:\n '{reason}'")
        except Exception as e:
            print(f'ERROR -> update_order_status user {e}')
        # отправляем менаджерам сообщение, что заказ отменён 
        admuns_get_message = sql_mgt.get_admins_by_rule('GET_INFO_MESSAGE', conn=conn)
        for admun_get_message in admuns_get_message:
            try:
                await bot.send_message(admun_get_message['tg_id'], f"Заказ {order_data['no']} был отменён.\n\nПо причине:\n '{reason}'")
            except Exception as e: 
                print(f'ERROR -> update_order_status Admin {e}')
    elif status == 'NEED_PAYMENTS':
        cancel_minet = additional_params.get('cancel_minet', 30)
        cancel_dt = datetime.now() + timedelta(minutes=cancel_minet)

        send_invoice_data = await pyments.buy_order_user_id(order_data, bot, additional_params.get('pyment_settings'))
        await sql_mgt.add_cancel_order(order_data['no'], init_user_id, send_invoice_data.chat.id, send_invoice_data.message_id, cancel_dt, conn=conn)

    if status != 'NEED_PAYMENTS':
        cancel_order = await sql_mgt.get_cancel_order(order_data['no'])
        if cancel_order != None:
            await sql_mgt.delete_cancel_order(order_data['no'])
            if status !=  'PAYMENT_SUCCESS':
                try:
                    await bot.delete_message(
                        chat_id=cancel_order['chat_id'],
                        message_id=cancel_order['pyment_message_id']
                    )
                except:
                    print('ERROR -> Сообщение уже удалено!')

    if sync_conn == None:
        await sql_mgt.update_order_status_sql_async(order_data['no'], status, conn=conn)
    else:
        sql_mgt.update_order_status_sql(order_data['no'], status, conn=sync_conn)        

    #if conn_inp == None:
    #    await conn.close()


# будем отменять все заказы, время которых истекло
async def cancel_old_orders():
    # должны получить все записи из новой таблицы
    cancel_orders = await sql_mgt.get_cancel_orders()
    #print('cancel_orders -> ', cancel_orders)
    # переместить заказ в отменённые 
    for cancel_order in cancel_orders:
        order = await sql_mgt.get_order(cancel_order['order_no'])
        await sql_mgt.delete_cancel_order(cancel_order['order_no'])
        
        if order['status'] == 'NEED_PAYMENTS':
            await update_order_status(cancel_order['user_tg_id'], order, 'CANCEL', 'Заказ не был оплачен и автоматически отменён', {})
        
            if DELETE_MESSAGES:
                try:
                    await global_objects.bot.delete_message(
                        chat_id=cancel_order['chat_id'],
                        message_id=cancel_order['pyment_message_id']
                    )
                except Exception:
                    print('ERROR -> Сообщение уже удалено!')
    #await global_objects.bot.send_message(1087624586, f"AAAAAAAaaaaaaa")
