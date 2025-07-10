from aiogram import Router, F
from aiogram.types import CallbackQuery

from heandlers import menu
#from sql_mgt import sql_mgt.set_param
from keyboards import subscriptions_kb
import sql_mgt
from keys import SPLITTER_STR


router = Router()
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)


async def mailing_to_all_subscribers(path_id:int):
    text_message = await get_mailing_text_to_all_subscribers(path_id)

    all_subscriptions = await sql_mgt.get_all_subscriptions_id()
    print('all_subscriptions -> ', all_subscriptions)
    for subscription in all_subscriptions[1:]:
        try:
            await global_objects.bot.send_message(int(subscription), text_message, reply_markup=subscriptions_kb.mailing_item_kb(True, path_id))
            await sql_mgt.set_param(subscription, 'DELETE_LAST_MESSAGE', 'yes')
        except Exception as e:
            print('ERROR ->', e)


async def get_mailing_text_to_all_subscribers(path_id:int) -> str:
    path = global_objects.tree_data.get_id_to_path(path_id)
    tree_item = global_objects.tree_data.get_obj_from_path(path)  
    tree_name = path.split(SPLITTER_STR)[-1]
    text_message = ''
    if tree_name:
        text_message = f'"{tree_name}"' 
    
    tree_item_text = tree_item.text
    if tree_item_text:
        text_message += '\n\n'
        text_message += tree_item_text

    return text_message

    