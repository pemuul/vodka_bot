from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand, BotCommandScopeDefault, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
import asyncio
import logging
import subprocess
import sqlite3
import os
import sys
import json

current_directory = os.path.dirname(os.path.abspath(__file__))
target_directory = os.path.join(current_directory, '../')
sys.path.insert(0, target_directory)
from sql.sql_site import append_fill_wallet_line

# Логирование для отслеживания событий
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
API_TOKEN = '7419016302:AAGHDIsBmFr5dMf6BuVeK3QgaH2VHaZR2vw'  # Замените на токен вашего бота
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
create_new_bot = False
create_new_bot_name = ''

# кошелёк
run_fill_wallet = False 
fill_wallet_bot_name = None

password_server = 'serverqwe123'

# ID пользователя, которому бот может отвечать
ALLOWED_USER_ID = 1087624586


commands = [
    BotCommand(command="/start", description="НАЧАТЬ")
]

class StartButtonBot(CallbackData, prefix='start_btn'):
    command: str
    id_com: int

class ButtonBot(CallbackData, prefix='bot_select'):
    command: str
    bot_name: str

class Create_New_Bot(CallbackData, prefix='new_b'):
    success: bool
    bot_name: str

class CommandBtn(CallbackData, prefix='com_b'):
    command: str

# Динамический список элементов
menu_items = [
    "Статус",
    "Остановить бота",
    "Запустить бота",
    "Вкл/Выкл Магазин",
    "Перезапустить бота",
    "Перезапустить всё",
    "Отрубить всё процессы",
    "Пополнить кошелёк"
]  # Этот список можно изменять по своему усмотрению


def create_new_bot_console(bot_name, tocken_bot) -> str:
    result = subprocess.run(f'sudo -S /home/server/create_new_bot.sh {bot_name} {tocken_bot}', shell=True, capture_output=True, input=password_server + "\n", text=True)
    print(result.stdout)
    return str(result.stdout)


def create_menu_keyboard(items):
    buttons = InlineKeyboardBuilder()

    for item_id, item in enumerate(items):
        buttons.button(text=item, callback_data=StartButtonBot(command=item, id_com=item_id))

    buttons.adjust(1)
    return buttons.as_markup()

def create_menu_bots_keyboard(bots, command):
    buttons = InlineKeyboardBuilder()

    for bot_id, bot in enumerate(bots):
        buttons.button(text=bot, callback_data=ButtonBot(command=command, bot_name=bot))

    buttons.adjust(1)
    return buttons.as_markup()

# Функция для отправки сообщений только разрешенному пользователю
async def send_to_allowed_user(message: Message) -> bool:
    if message.from_user.id == ALLOWED_USER_ID:
        return True
    else:
        await message.answer("Переходите в @Easy_TG_Shop_Bot")
        return False

# Хендлер на команду /start
@dp.message(Command("start"))
async def start_command(message: Message):
    if await send_to_allowed_user(message):
        menu_keyboard = create_menu_keyboard(menu_items)
        await message.answer("Привет! Вот меню:", reply_markup=menu_keyboard)

# Хендлер для удаления клавиатуры
@dp.message(Command("remove_keyboard"))
async def remove_keyboard(message: Message):
    if await send_to_allowed_user(message):
        await message.answer("Клавиатура удалена.", reply_markup=ReplyKeyboardRemove())

# Хендлер на команду /menu
@dp.message(Command("menu"))
async def menu_command(message: Message):
    if await send_to_allowed_user(message):
        menu_keyboard = create_menu_keyboard(menu_items)
        await message.answer("Вот меню:", reply_markup=menu_keyboard)

def get_supervisorctl_status(password=password_server):
    result = subprocess.run('sudo -S supervisorctl status', shell=True, capture_output=True, input=password + "\n", text=True)
    print(result.stdout)
    lines = str(result.stdout).strip().split('\n')
    processes = []
    for line in lines:
        parts = line.split()
        process = {
            "name": parts[0],
            "state": parts[1],
            "pid": int(parts[3].strip(',')) if parts[1] == 'RUNNING' else None,
            "uptime": ' '.join(parts[4:]) if parts[1] == 'RUNNING' else None
        }
        processes.append(process)
    print(processes)

    return processes

# Хендлер для обработки нажатий на inline-кнопки
@dp.callback_query(StartButtonBot.filter())
async def handle_callback(callback: CallbackQuery, callback_data: StartButtonBot):
    #item_name = callback_data.data[2:]  # Убираем префикс "b_"
    #print(callback_data.command)
    #await callback.message.answer(f"Вы нажали на {callback_data.command} {callback_data.id_com}")
    # Подтверждаем обработку коллбэка, чтобы кнопки не оставались активными
    await callback.answer()
    if callback_data.command == 'Статус':
        #subprocess.run(f'sudo -S supervisorctl stop {process_name}')
        bots = get_supervisorctl_status()
        ret_text = ''
        # Устанавливаем ширину столбцов для красивого вывода
        name_width = max(len(item['name']) for item in bots)
        state_width = max(len(item['state']) for item in bots)

        # Заголовок
        ret_text += f"{'Name'.ljust(name_width)} | {'State'.ljust(state_width)} | Uptime\n"
        ret_text += '-' * (name_width + state_width + 11) + '\n'

        # Вывод данных
        for item in bots:
            name = item['name']
            state = item['state']
            uptime = item['uptime'] if item['uptime'] else 'N/A'
            ret_text += f"{name.ljust(name_width)} | {state.ljust(state_width)} | {uptime}\n"

        ret_text = f"```\n{ret_text}```"
        
        await callback.message.edit_text(ret_text, reply_markup=create_menu_keyboard(menu_items), parse_mode=ParseMode.MARKDOWN_V2)        
    elif callback_data.command in [
        "Остановить бота",
        "Запустить бота",
        "Перезапустить бота",
        "Перезапустить всё",
        "Вкл/Выкл Магазин"
    ]:
        if callback_data.command == 'Остановить бота':
            command = 'stop'
        elif callback_data.command == 'Запустить бота':
            command = 'start'
        elif callback_data.command == 'Перезапустить бота':
            command = 'restart'
        elif callback_data.command == 'Перезапустить всё':
            command = 'reload'
        elif callback_data.command == "Вкл/Выкл Магазин":
            command = 'on_off_market'

        if command == 'reload':
            await callback.message.edit_text('ВСЁ ПЕРЕЗАПУЩЕННО', reply_markup=create_menu_keyboard(menu_items))
            subprocess.run(f'sudo -S supervisorctl reload', shell=True, input=password_server + "\n", text=True)
            return
    
        supervisorctl_status = get_supervisorctl_status()
        bots_name = [bot['name'] for bot in supervisorctl_status] + ['ОТМЕНА']
        await callback.message.edit_text(f'Выберите бота для "{command}"', reply_markup=create_menu_bots_keyboard(bots_name, command))

        #subprocess.run('sudo -S supervisorctl status', shell=True, capture_output=True, input=password + "\n", text=True)
    elif callback_data.command == 'Отрубить всё процессы':
        await callback.message.edit_text('ВСЕ ПРОЦЕССЫ ПЕРЕЗАПУЩЕННЫ', reply_markup=create_menu_keyboard(menu_items))
        subprocess.run("ls -l", shell=True)
        subprocess.run(f'pkill python', shell=True)
        subprocess.run(f'pkill python3', shell=True) 
        subprocess.run(f'pkill gunicorn', shell=True)  
    elif callback_data.command == 'Пополнить кошелёк':
        supervisorctl_status = get_supervisorctl_status()
        bots_name = [bot['name'] for bot in supervisorctl_status] + ['ОТМЕНА']

        command = 'fill_wallet'

        await callback.message.edit_text(f'Выберите бота для пополнения', reply_markup=create_menu_bots_keyboard(bots_name, command))

@dp.callback_query(ButtonBot.filter())
async def handle_bot_callback(callback: CallbackQuery, callback_data: ButtonBot):
    global run_fill_wallet
    global fill_wallet_bot_name

    command = callback_data.command
    if callback_data.bot_name == 'ОТМЕНА':
        run_fill_wallet = False
        fill_wallet_bot_name = None
        
        await callback.message.edit_text("Вот меню:", reply_markup=create_menu_keyboard(menu_items))
        return
    # пополняем кошелёк
    elif callback_data.command == 'fill_wallet':
        fill_wallet_bot_name = callback_data.bot_name
        run_fill_wallet = True

        question = InlineKeyboardBuilder()
        question.button(text='ОТМЕНА', callback_data=ButtonBot(command='ОТМЕНА', bot_name='ОТМЕНА'))
        question.adjust(1)
        await callback.message.edit_text(f"Введите число пополнения:", reply_markup=question.as_markup())
        #await callback.message.edit_text("Введите число пополнения:", reply_markup=create_menu_keyboard(menu_items))
        return
    elif callback_data.command == 'on_off_market': 
        on_off = on_off_market(callback_data.bot_name)
        await callback.message.edit_text(f"Бот Магазин бота Активен: {on_off}", reply_markup=create_menu_keyboard(menu_items))
        return
    
    subprocess.run(f'sudo -S supervisorctl {command} {callback_data.bot_name}', shell=True, capture_output=True, input=password_server + "\n", text=True)

    await callback.message.edit_text(f"Бот {callback_data.bot_name} {command}", reply_markup=create_menu_keyboard(menu_items))


@dp.callback_query(CommandBtn.filter())
async def handle_CommandBtn_callback(callback: CallbackQuery, callback_data: CommandBtn):
    if callback_data.command == 'delete':
        bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)

@dp.callback_query(Create_New_Bot.filter())
async def handle_Create_New_Bot_callback(callback: CallbackQuery, callback_data: Create_New_Bot):
    global create_new_bot
    global create_new_bot_name

    if not callback_data.success:
        create_new_bot = False
        bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)

    create_new_bot = True
    create_new_bot_name = callback_data.bot_name

    cancel = InlineKeyboardBuilder()
    cancel.button(text='ОТМЕНА', callback_data=Create_New_Bot(success=False, bot_name='None'))
    cancel.adjust(1)

    await callback.message.edit_text("Отправте токен бота!", reply_markup=cancel.as_markup())

# Хендлер на все остальные сообщения
@dp.message(F.text)
async def echo(message: Message):
    if not await send_to_allowed_user(message):
        return
    
    global create_new_bot
    global run_fill_wallet

    if create_new_bot:
        ret_text = create_new_bot_console(create_new_bot_name, message.text)
        await message.answer(ret_text)
        create_new_bot = False
        return
    
    if run_fill_wallet:
        global fill_wallet_bot_name
        ret_text = fill_wallet(int(message.text), fill_wallet_bot_name)
        await message.answer(ret_text)
        run_fill_wallet = False
        return
    
    message_text  = message.text 
    if message_text[0] != '@':
        await message.answer('Приглите название бота!')
        return
    message_text = message_text[1:]

    conf_dir = '/etc/supervisor/conf.d'
    result = subprocess.run(f'ls {conf_dir}', shell=True, capture_output=True, text=True)
    configs = str(result.stdout).strip().split()
    configs_name = [config[:-5] for config in configs]
    if message_text not in configs_name:
        question = InlineKeyboardBuilder()

        question.button(text='ДА', callback_data=Create_New_Bot(success=True, bot_name=message_text))
        question.button(text='НЕТ', callback_data=Create_New_Bot(success=False, bot_name=message_text))

        question.adjust(1)
        await message.answer(f"Запустить нового бота: @{message_text} ?", reply_markup=question.as_markup())
        return 

    menu_buttons = [
        'stop',
        'start',
        'restart',
        'ОТМЕНА'
    ]
    buttons = InlineKeyboardBuilder()

    for menu_button in menu_buttons:
        buttons.button(text=menu_button, callback_data=ButtonBot(command=menu_button, bot_name=message_text))

    buttons.adjust(1)
    await message.answer(f"Что сделать с ботом: @{message_text}", reply_markup=buttons.as_markup())


def get_bot_directory(bot_name):
    conf_dir = '/etc/supervisor/conf.d/' + bot_name + '.conf'
    result = subprocess.run(f'cat {conf_dir}', shell=True, capture_output=True, text=True)
    lines = str(result.stdout).strip().split()
    directory = [line[10:] for line in lines if line[:10] == 'directory='][0]
    
    return directory

def fill_wallet(amount, bot_name):
    directory = get_bot_directory(bot_name)
    db_file = directory + '/tg_base.sqlite' 

    #asyncio.run(succesfull_payment_wallet())
    user_id = 1087624586
    conn = sqlite3.connect(db_file)  
    try:
        wallet_data = append_fill_wallet_line(user_id, 'FILL_WALLET', '', f'Пополнение кошелька на сумму {amount}', amount, conn)
        print('wallet_data', wallet_data)
    except Exception as e:
        print('ERROR -> ', e)

    conn.close()

    return "Бот пополнен"


def on_off_market(bot_name):
    directory = get_bot_directory(bot_name)
    settings_json_dir = directory + '/settings.json'

    with open(settings_json_dir, 'r') as f:
        settings_bot = json.load(f)

    settings_bot['site']['site_on'] = not settings_bot['site']['site_on']

    with open(settings_json_dir, 'w') as file:
        json.dump(settings_bot, file, ensure_ascii=False, indent=4)

    subprocess.run(f'sudo -S supervisorctl restart {bot_name}', shell=True, capture_output=True, input=password_server + "\n", text=True)

    return settings_bot['site']['site_on']



# Функция запуска бота
async def main():
    #await bot.delete_webhook(drop_pending_updates=True)  # Очищаем вебхуки и неполученные обновления
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await dp.start_polling(bot)  # Запуск long polling

if __name__ == "__main__":
    print('run bot')
    asyncio.run(main())
