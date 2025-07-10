from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, FSInputFile
from aiogram.enums import ParseMode
import os
import sys

from heandlers import menu, pyments, web_market, settings_bot
#from keys import ADMIN_ID_LIST
import sql_mgt
#from sql_mgt import sql_mgt.insert_user, sql_mgt.get_visit, sql_mgt.set_param, sql_mgt.get_users_per_day, sql_mgt.add_admin, sql_mgt.is_normal_invite_admin_key, sql_mgt.get_last_order
#from heandlers.web_market import start, send_item_message
#from site_bot.orders_mgt import get_all_data_order


router = Router()  # [1]
global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    menu.init_object(global_objects)
    pyments.init_object(global_objects)
    web_market.init_object(global_objects)
    sql_mgt.init_object(global_objects)
    settings_bot.init_object(global_objects)
    create_def_cmd(global_objects.command_dict)


async def delete_answer_messages(message: Message) -> dict:
    delete_answer_messages_str = await sql_mgt.get_param(message.chat.id, 'DELETE_ANSWER_LEATER')
    delete_answer_messages = delete_answer_messages_str.split(',')
    for delete_answer_message in delete_answer_messages:
        if delete_answer_message != '':
            try:
                await global_objects.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=int(delete_answer_message)
                )
            except Exception as e:
                print(f'Ошибка1: {e}')
    await sql_mgt.set_param(message.chat.id, 'DELETE_ANSWER_LEATER', '')


async def delete_this_message(message: Message):
    await global_objects.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)


async def delete_answer_leater(answer_message: Message):
    await sql_mgt.append_param_get_old(answer_message.chat.id, 'DELETE_ANSWER_LEATER', answer_message.message_id)


@router.message(Command("start"))
async def command_start_handler(message: Message) -> None:
    #await message.answer("У вас нет прав администратора")
    #command_text = message.get_command()
    message_text = message.text
    if not message_text:
        message_text = '/start' 

    atter = message_text.split(' ')
    if len(atter) > 1:
        params = atter[1].split('_')

        if params[0] == 'item':
            print(params[1])
            await web_market.send_item_message(int(params[1]), message)
            await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
            #return
        else:
            if not await add_admin_from_key(message.chat.id, atter[1]):
                answer_message = await message.answer("Не вышло:(\nЛибо время ссылки истекло, либо ею уже кто-то воспользовался\n\nЗапросите новую ссылку")
                await delete_answer_leater(answer_message)
                await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
                #return
            else:
                await menu.get_message(message)
                await sql_mgt.insert_user(message)
                await set_commands()
                return
    else:
        await set_commands()

        user = await sql_mgt.get_user_async(message.chat.id)
        if user:
            if not user.get('age_18'):
                answer_message = await message.answer("Вы не подтвердили, что вам есть 18 лет!\n\nДля продолжения работы с ботом, нажмите на кнопку ниже")

        await menu.get_message(message)
        
    #return 
    await sql_mgt.insert_user(message)
    await set_commands()
    await delete_this_message(message)


def create_def_cmd(def_list:dict):
    command_name = list(def_list.keys())
    if len(command_name) > 0:
        @router.message(Command(*command_name))
        async def cmd_test(message: Message):
            answer_message = await message.answer(def_list.get(str(message.text)[1:]).get('text'), parse_mode=ParseMode.HTML)
            await delete_answer_leater(answer_message)
            #await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
            await delete_this_message(message)


@router.message(Command("menu"))
async def cmd_start(message: Message):
    await set_commands()
    await menu.get_message(message)
    await delete_this_message(message)


@router.message(Command("about_bot"))
async def cmd_about_bot(message: Message):
    answer_message = await message.answer("По техническим вопросам, можете обращаться к нашему менаджеру:\n@Pemuul\n\nЕсли вас интересует запуск подобного бота, то вы можете перейти сюда:\n@Easy_TG_Shop_Bot\n\nТут вы сможете подробнее ознакомиться с нашей услугой и изучить инструкцию администрирования!")
    await delete_answer_leater(answer_message)
    await delete_this_message(message)


@router.message(Command("set_admin_help"))
async def cmd_set_admin_help(message: Message):
    answer_message = await message.answer('', parse_mode=ParseMode.HTML)
    await delete_answer_leater(answer_message)
    await delete_this_message(message)


@router.message(Command("my_id"))
async def cmd_my_id(message: Message):
    answer_message = await message.answer(str(message.chat.id))
    await delete_answer_leater(answer_message)
    await delete_this_message(message)


@router.message(Command("get_log_click"))
async def cmd_get_log_click(message: Message, find_day:int=10):   
    if message.chat.id not in global_objects.admin_list:
        return

    visit_list = await sql_mgt.get_visit(find_day)
    return_text = 'Тыкнули на меню за последние 10 дней:\n'
    for visit in visit_list:
        return_text += f'  {visit[0]} - {visit[1]} раз\n'
    await message.answer(return_text)

    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
    #await delete_this_message(message)


@router.message(Command("get_log_visit"))
async def cmd_get_log_visit(message: Message, find_day:int=10):
    if message.chat.id not in global_objects.admin_list:
        return

    visit_list = await sql_mgt.get_users_per_day(find_day)
    return_text = 'Число пользователей в день, за последние 10 дней:\n'
    for visit in visit_list:
        return_text += f'  {visit[0]} - {visit[1]} человек\n'
    await message.answer(return_text)

    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
    #await delete_this_message(message)


@router.message(Command("market"))
async def cmd_mrket(message: Message):
    if not global_objects.settings_bot.get('site').get('site_on'):
        answer_message = await message.answer('Магазин отключён в этом боте!')
        await delete_answer_leater(answer_message)
        await delete_this_message(message)
        return

    await web_market.start(message)
    #await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
    await delete_this_message(message)



@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await settings_bot.get_settings_msg(message)
    await delete_this_message(message)


@router.message(Command("get_url"))
async def cmd_get_url(message: Message):   
    if message.chat.id not in global_objects.admin_list:
        return
    
    current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
    encode_directory_b = web_market.encrypt_text_by_key(current_directory)
    encode_directory = encode_directory_b.decode('utf-8')

    answer_message = await message.answer(encode_directory)
    await delete_answer_leater(answer_message)

    await delete_this_message(message)


@router.message(Command("get_json"))
async def cmd_get_json(message: Message):   
    if message.chat.id not in global_objects.admin_list:
        return
    
    current_directory = os.path.abspath(os.path.dirname(sys.argv[0]))
    document = FSInputFile(current_directory + '/tree_data.json')
    await message.answer_document(document)

    await delete_this_message(message)


async def set_commands():
    commands = [
        BotCommand(
            command='menu',
            description='Меню (Начало)'
        )
    ]

    commands_name = list(global_objects.command_dict.keys())
    for command in commands_name:
        commands.append(
                BotCommand(
                    command=command,
                    description=global_objects.command_dict.get(command).get('description')
                )
            )
        
    commands.append(
            BotCommand(
            command='settings',
            description='Настройки'
        )
    )

    commands.append(
            BotCommand(
            command='about_bot',
            description='О боте'
        )
    )

    if global_objects.settings_bot.get('site').get('site_on'):
        commands.append(
                BotCommand(
                command='market',
                description='🎪 Магазин 🎪'
            )
        )

    await global_objects.bot.set_my_commands(commands, BotCommandScopeDefault())
        


async def add_admin_from_key(chat_id:int, key: str) -> bool:
    user_create_id = await sql_mgt.is_normal_invite_admin_key(key)
    if user_create_id:
        await sql_mgt.add_admin(chat_id, user_create_id)
        global_objects.admin_list.append(chat_id)
        return True
    
    return False