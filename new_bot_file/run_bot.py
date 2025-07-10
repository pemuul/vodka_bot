import sys
import os
import json

with open('settings.json', 'r') as f:
    # Загружаем данные из файла
    settings_bot = json.load(f)
    version_bot = settings_bot['VERSION_BOT']

current_directory = os.path.dirname(os.path.abspath(__file__))
target_directory = os.path.join(current_directory, f'../../{version_bot}')
sys.path.insert(0, target_directory)

from bot import run_bot

ADMIN_ID_LIST = [1087624586] 

command_dict = settings_bot.get("commands")
settings_bot['run_directory'] = current_directory
TELEGRAM_BOT_TOKEN = settings_bot['TELEGRAM_BOT_TOKEN']

run_bot(TELEGRAM_BOT_TOKEN, ADMIN_ID_LIST, command_dict, settings_bot)