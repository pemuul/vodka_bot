import sys
import os

# Получаем текущую директорию
current_directory = os.path.dirname(os.path.abspath(__file__))

# Путь к целевой папке
target_directory = os.path.join(current_directory, './information_telegram_bot')

# Добавляем целевую папку в sys.path
sys.path.insert(0, target_directory)

from bot import run_bot

TELEGRAM_BOT_TOKEN = '6853605701:AAGjBUGFgLgHgAafGdqG-gb3KCiXytt8BUI' 
ADMIN_ID_LIST = [1087624586] 

command_dict = {
    "help" : {
        'text': 'По любым предложениям, помощи, корректировке информации вежливо обращаться к админу @stupuraiter💌',
        "description": "Помощь"
    },
    "promote" : {
        'text': 'Если вы проводите мероприятие на острове Ольхон, свяжитесь с админом @stupuraiter и мы добавим его в список событий.*💌)\n\nДля упрощения, создайте пост в канале и отправте ссылку на него!',
        "description": "Предложить своё мероприятие"
    },
    "support_project" : {
        'text': 'Понравился бот? Нашли важную для себя информацию и хотели бы поблагодарить команду?\nЛюбую сумму можно отправить по ссылке <a href=\"https://www.tinkoff.ru/cf/2NHCUrarLXZ\">Регина С.</a>',
        "description": "Поддержать проект💫"
    }
}
run_bot(TELEGRAM_BOT_TOKEN, ADMIN_ID_LIST, command_dict)