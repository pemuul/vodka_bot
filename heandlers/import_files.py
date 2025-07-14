import os
import shutil
from pathlib import Path
import time

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BotCommand, BotCommandScopeDefault, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.types.input_file import FSInputFile

from heandlers import media_heandler
import sql_mgt
from keys import MAIN_JSON_FILE
#from sql_mgt import get_last_media_and_set_next


router = Router() 

global_objects = None

def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    media_heandler.global_objects = global_objects
    media_heandler.sql_mgt.init_object(global_objects)
    sql_mgt.init_object(global_objects)

    

''' Подгрузка и обновление файлов '''
# ======================================================================
@router.message(Command('get_data_file'))
async def send_data_file(message: Message):
    if not message.chat.id in global_objects.admin_list:
        await message.answer("У вас нет прав администратора")
        return
    # Отправляем файл пользователю
    document = FSInputFile('tree_data.json')
    await global_objects.bot.send_document(message.chat.id, document)


def get_next_filename(folder_path='./load_files/', base_filename='data_tree_'):
    # Получаем список файлов в указанной папке
    existing_files = os.listdir(folder_path)

    # Формируем список файлов, которые начинаются с базового имени
    matching_files = [file for file in existing_files if file.startswith(base_filename)]

    # Если нет соответствующих файлов, возвращаем базовое имя
    if not matching_files:
        return base_filename + '0'

    # Иначе, находим максимальный индекс
    max_index = max([int(file[len(base_filename):-len(os.path.splitext(file)[1])] or 0) for file in matching_files])

    # Формируем следующее имя файла
    next_filename = f"{base_filename}{max_index + 1}"

    return next_filename


#@dp.message.register(F.from_user.id.in_({1087624586}) & F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO}))
@router.message(F.document)
async def get_admin_message(message: Message):
    if not message.chat.id in global_objects.admin_list:
        await message.answer("У вас нет прав администратора")
        return

    # if admin is viewing rules section and sends a PDF, store it as the rules file
    if message.document.mime_type == "application/pdf":
        current_path_id = await sql_mgt.get_param(message.chat.id, "CURRENT_PATH_ID")
        if current_path_id:
            path = global_objects.tree_data.get_id_to_path(int(current_path_id))
            tree_item = global_objects.tree_data.get_obj_from_path(path)
            if tree_item.item_id == "rule":
                file = await global_objects.bot.download(message.document.file_id)
                fname = f"rules_{int(time.time())}.pdf"
                dest_dir = Path(__file__).resolve().parent.parent / "site_bot" / "static" / "uploads"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / fname
                with dest.open("wb") as f:
                    f.write(file.getvalue())
                web_path = f"/static/uploads/{fname}"
                await sql_mgt.set_param(0, "RULE_PDF", web_path)
                await message.answer("Файл правил обновлён")
                return
    
    if message.document.mime_type in ['image/gif', 'video/mp4']:
        await media_heandler.set_video_file(message)
        return

    file_name = message.document.file_name
    expansion_file = file_name.split('.')[-1]
    if expansion_file != 'json':
        await message.answer("Не знаю, что с этим делать(")
        return
    
    file = await global_objects.bot.get_file(message.document.file_id)
    new_file_name = get_next_filename() + '.json'

    downloaded_file = await global_objects.bot.download_file(file.file_path, './load_files/' + new_file_name)
    buttons = [[
        InlineKeyboardButton(text='Да', callback_data=f"dowlandfile_yes_{new_file_name}"), 
        InlineKeyboardButton(text='Нет', callback_data=f"dowlandfile_no{new_file_name}")
    ]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text_message = f'Загрузить данные из файла {file_name}?' 
    last_message = await message.answer(text_message, reply_markup=keyboard)


@router.callback_query(F.data.startswith("dowlandfile_"))
async def callbacks_num(callback: CallbackQuery):
    data_split = callback.data.split("_")
    if data_split[1] == "yes":
        await load_file(callback, data_split)  

    await global_objects.bot.delete_message(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id
    )
    

async def load_file(callback, data_split):
    file_name = '_'.join(data_split[2:])
    error_tree_data = global_objects.tree_data.check_json_file_valid('./load_files/' + file_name, get_error=True)
    if len(error_tree_data) > 0:
        await callback.message.answer('Исправте ошибки и загрузите файл ещё раз:\n ' + str(error_tree_data))
        return

    os.remove(MAIN_JSON_FILE)
    shutil.copy('./load_files/' + file_name, MAIN_JSON_FILE)
    
    #load_data()
    global_objects.tree_data.create_obj_data_from_json(MAIN_JSON_FILE)
    await callback.message.answer('Данные успешно обновлены!')


async def find_last_file_and_increment(folder_path):
    # Получаем список файлов в указанной папке
    files = os.listdir(folder_path)

    # Отфильтруем только файлы, без подпапок
    files = [f for f in files if os.path.isfile(os.path.join(folder_path, f))]

    # Если список файлов не пуст, сортируем его по имени файла
    if files:
        files.sort()

        # Выбираем последний файл
        last_file = files[-1]

        # Извлекаем цифры из названия файла и прибавляем единицу
        try:
            file_number = int(''.join(filter(str.isdigit, last_file)))
            next_number = file_number + 1
            return next_number
        except ValueError:
            print("Невозможно извлечь число из названия файла.")
            return None
    else:
        print("В указанной папке нет файлов.")
        return None

'''
@router.message(F.photo)
async def get_admin_photo(message: Message):
    if not message.chat.id in ADMIN_ID_LIST:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return
    
    #async with file_lock:
'''

async def set_new_image(message):
    await global_objects.bot.send_message(message.from_user.id, f"У фото название:\n{message.photo[0].file_id}", reply_to_message_id=message.message_id)
    #await message.answer(f"У фоторо название {next_file_id}")
# ======================================================================


''' Откатываем изменение нахазад '''
# ======================================================================
async def return_last_edit() -> str:

    last_file = await find_last_file('./load_files/', -1)
    upload_file = await find_last_file('./load_files/')

    if not upload_file:
        return 'Больше откатить невозможно'

    if not last_file:
        return 'Нет файла чтобы откатить'


    os.remove(last_file)
    os.remove(MAIN_JSON_FILE)
    shutil.copy(upload_file, MAIN_JSON_FILE)
    
    global_objects.tree_data.create_obj_data_from_json(MAIN_JSON_FILE)
    return 'Вы откатили изменение!'



async def find_last_file(folder_path:str, find_id:int=-2):
    try:
        # Получаем список файлов в папке
        files = os.listdir(folder_path)
        
        # Фильтруем только файлы с заданным расширением (например, .json)
        files = [f for f in files if f.endswith('.json')]
        
        # Сортируем файлы по имени (порядок сортировки зависит от вашего конкретного случая)
        files.sort(key=lambda f: os.path.getmtime(os.path.join(folder_path, f)), reverse=False)
        
        # Если список файлов не пустой, возвращаем последний файл
        if files:
            return os.path.join(folder_path, files[find_id])
        else:
            return None  # Если нет файлов с нужным расширением
    except Exception as e:
        print(f"Error: {e}")
        return None

# ======================================================================