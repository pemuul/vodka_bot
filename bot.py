import asyncio
import concurrent.futures
import logging
import sys
import signal
import datetime
import multiprocessing
import time
import json
import os

from aiogram import Bot, Dispatcher, Router, types, F, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod, Response, GetUpdates, SendMessage
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineQuery,
    Message,
    PollAnswer,
    PreCheckoutQuery,
    ShippingQuery,
    TelegramObject,
    Update,
    InputMedia,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    PhotoSize,
    Document,
    Video,
    Audio,
    Voice,
    VideoNote,
    Sticker,
    Animation,
)
from typing import Any, Type, Optional, List, Dict, Callable, Awaitable


from keys import MAIN_JSON_FILE
from json_data_mgt import Tree_data, TreeObject, copy_or_rename_file, create_folder
#from sql_mgt import sql_mgt.create_db_file, sql_mgt.upload_admins, sql_mgt.get_admins_id, sql_mgt.init_wallet
import sql_mgt
from pyment_bot_dir.pyment_mgt import monthly_payment_with_conn

from heandlers import commands, answer_button_menu, import_files, text_heandler, admin_answer_button, media_heandler, pyments, order, answer_button_settings, answer_button_subscription, confirm_age_phone

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


################################################################################
# 1.  ЛОГ outbound — остаётся почти без изменений
################################################################################
class RequestLogger(BaseRequestMiddleware):
    def __init__(self, ignore: Optional[List[Type[TelegramMethod[Any]]]] = None):
        self.ignore = ignore or []

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType,
        bot: Bot,
        method: TelegramMethod[Any],
        *args, **kwargs
    ) -> Any:
        # пропускаем системные методы
        if type(method) not in self.ignore:
            chat_id = getattr(method, "chat_id", None)
            if chat_id is not None:
                # 1) текст
                text = getattr(method, "text", None)

                if text:
                    # 2) кнопки
                    buttons: List[Dict[str, Any]] = []
                    markup = getattr(method, "reply_markup", None)
                    if isinstance(markup, InlineKeyboardMarkup):
                        for row in markup.inline_keyboard:  # List[List[InlineKeyboardButton]]
                            for btn in row:
                                buttons.append({
                                    "text":         btn.text,
                                    "callback_data": getattr(btn, "callback_data", None),
                                    "url":          getattr(btn, "url", None),
                                    "web_app_url":  getattr(getattr(btn, "web_app", None), "url", None),
                                })

                    # 3) медиа
                    media_list: List[Dict[str, Any]] = []
                    media = getattr(method, "media", None)
                    # media может быть одним InputMedia или списком
                    items = media if isinstance(media, list) else [media] if media else []
                    for m in items:
                        if isinstance(m, InputMedia):
                            media_list.append({
                                "type":    m.type.value if hasattr(m.type, "value") else m.type,
                                "media":   m.media,
                                "caption": m.caption,
                            })

                    # сохраняем в БД одной строкой
                    #print(method)
                    await sql_mgt.add_participant_message(
                        user_tg_id=chat_id,
                        sender="admin",
                        text=text,
                        buttons=buttons or None,
                        media=media_list or None,
                    )

        # дальше отправляем сам запрос
        return await make_request(bot, method, *args, **kwargs)


class IncomingLogger(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # 1) Обычные текстовые сообщения от пользователя
        if isinstance(event, Message):
            user = event.from_user
            if user and event.text:
                await sql_mgt.add_participant_message(
                    user_tg_id=user.id,
                    sender="user",
                    text=event.text
                )

        # 2) Нажатия на inline-кнопки (CallbackQuery)
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            cb_data = event.data or ""
            btn_text: Optional[str] = None

            # Ищем текст кнопки среди inline-кнопок сообщения
            markup = getattr(event.message, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                for row in markup.inline_keyboard:
                    for btn in row:
                        if btn.callback_data == cb_data:
                            btn_text = btn.text
                            break
                    if btn_text is not None:
                        break

            # Сохраняем в БД факт нажатия кнопки
            await sql_mgt.add_participant_message(
                user_tg_id=user.id,
                sender="user",
                text="",  # нет обычного текста
                buttons=[{"text": btn_text, "callback_data": cb_data}]
            )

            # ВАЖНО: подтвердить колбэк, иначе в UI будет крутиться прелоадер
            await event.answer()

        # 3) Всё остальное — пропускаем
        return await handler(event, data)
    

class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Any],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        # --- ВСЕ входящие обновления приходят сюда ---
        # Если это сообщение — разбираем всё медиа
        if event.message:
            msg: Message = event.message
            user_id = msg.from_user.id
            text = msg.text or msg.caption or None

            # Кнопки
            buttons: List[Dict[str, Any]] = []
            if isinstance(msg.reply_markup, InlineKeyboardMarkup):
                for row in msg.reply_markup.inline_keyboard:
                    for btn in row:
                        buttons.append({
                            "text":          btn.text,
                            "callback_data": btn.callback_data,
                            "url":           btn.url,
                            "web_app_url":   getattr(getattr(btn, "web_app", None), "url", None),
                        })

            # Медиа
            media: List[Dict[str, Any]] = []

            # Фото
            if msg.photo:
                largest: PhotoSize = msg.photo[-1]
                if largest.file_size <= MAX_FILE_SIZE:
                    media.append({
                        "type":      "photo",
                        "file_id":   largest.file_id,
                        "file_size": largest.file_size,
                    })

            # Документ
            if msg.document and msg.document.file_size <= MAX_FILE_SIZE:
                doc: Document = msg.document
                media.append({
                    "type":      "document",
                    "file_id":   doc.file_id,
                    "file_size": doc.file_size,
                    "file_name": doc.file_name,
                    "mime_type": doc.mime_type,
                })

            # Видео
            if msg.video and msg.video.file_size <= MAX_FILE_SIZE:
                vid: Video = msg.video
                media.append({
                    "type":      "video",
                    "file_id":   vid.file_id,
                    "file_size": vid.file_size,
                    "duration":  vid.duration,
                })

            # Аудио
            if msg.audio and msg.audio.file_size <= MAX_FILE_SIZE:
                aud: Audio = msg.audio
                media.append({
                    "type":      "audio",
                    "file_id":   aud.file_id,
                    "file_size": aud.file_size,
                    "duration":  aud.duration,
                })

            # Голосовое
            if msg.voice and msg.voice.file_size <= MAX_FILE_SIZE:
                vc: Voice = msg.voice
                media.append({
                    "type":      "voice",
                    "file_id":   vc.file_id,
                    "file_size": vc.file_size,
                    "duration":  vc.duration,
                })

            # Гифка (animation)
            if msg.animation and msg.animation.file_size <= MAX_FILE_SIZE:
                an: Animation = msg.animation
                media.append({
                    "type":      "animation",
                    "file_id":   an.file_id,
                    "file_size": an.file_size,
                    "duration":  an.duration,
                    "file_name": an.file_name,
                })

            # Стикер
            if msg.sticker and (msg.sticker.file_size or 0) <= MAX_FILE_SIZE:
                st: Sticker = msg.sticker
                media.append({
                    "type":      "sticker",
                    "file_id":   st.file_id,
                    "file_size": st.file_size,
                    "emoji":     st.emoji,
                })

            # Кружок (video_note)
            if msg.video_note and msg.video_note.file_size <= MAX_FILE_SIZE:
                vn: VideoNote = msg.video_note
                media.append({
                    "type":      "video_note",
                    "file_id":   vn.file_id,
                    "file_size": vn.file_size,
                    "duration":  vn.duration,
                })

            # Сохраняем всё это в таблице participant_messages
            await sql_mgt.add_participant_message(
                user_tg_id=user_id,
                sender="user",
                text=text,
                buttons=buttons or None,
                media=media or None,
            )

        # --- Нажатие на inline-кнопку тоже приходит в Update ---
        if event.callback_query:
            cq: CallbackQuery = event.callback_query
            user_id = cq.from_user.id
            data_ = cq.data or ""
            btn_text: Optional[str] = None

            # Ищем текст кнопки
            markup = getattr(cq.message, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                for row in markup.inline_keyboard:
                    for btn in row:
                        if btn.callback_data == data_:
                            btn_text = btn.text
                            break
                    if btn_text:
                        break

            await sql_mgt.add_participant_message(
                user_tg_id=user_id,
                sender="user",
                text="",
                buttons=[{"text": btn_text, "callback_data": data_}],
            )
            await cq.answer()

        # Передаём апдейт дальше по цепочке
        return await handler(event, data)

class GlobalObjects:
    tree_data:TreeObject
    bot:Bot
    admin_list:list
    dp:Dispatcher
    command_dict:dict
    settings_bot:dict
    pyment_bot_settings:dict

    def __init__(self, tree_data, bot, admin_list, dp, command_dict, settings_bot) -> None:
        self.tree_data = tree_data
        self.bot = bot
        self.admin_list = admin_list
        self.dp = dp
        self.command_dict = command_dict
        self.settings_bot = settings_bot



global_objects:GlobalObjects


async def init_other_object(other_object):
    other_object.init_object(global_objects)
    global_objects.dp.include_router(other_object.router)


# Ставим рестарт бота на определённое время
def set_restart(hour, minet):
    def timeout_handler(signum, frame): 
        raise RuntimeError("Плановый рестарт")
    
    # Установка обработчика сигнала SIGALRM
    signal.signal(signal.SIGALRM, timeout_handler)

    # Получаем текущую дату и время
    now = datetime.datetime.now()

    # Если текущее время уже позже указанного, то прибавляем 1 день
    if now.hour > hour or (now.hour == hour and now.minute >= minet):
        tomorrow = now + datetime.timedelta(days=1)
        target_time = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minet)
    else:
        target_time = datetime.datetime(now.year, now.month, now.day, hour, minet)

    # Разница между текущим временем и целевым временем в секундах
    time_difference = target_time - now
    seconds_until_target = time_difference.total_seconds()

    print(f"До рестарта {int(seconds_until_target)} секунд")

    # Устанавливаем таймер
    print(seconds_until_target)
    signal.alarm(int(seconds_until_target))


# запускаем процесс, который будет отменять старые заказы
def run_order_delete_process():
    global background
    background = multiprocessing.Process(target=background_process)
    background.daemon = True  # Установка флага daemon в True
    background.start()


def background_process():
    loop = asyncio.new_event_loop()  # Create a new event loop
    asyncio.set_event_loop(loop)     # Set it as the current event loop

    while True:
        try:
            loop.run_until_complete(order.cancel_old_orders())
        except Exception as e:
            print('ERROR -> ', e)

        time.sleep(30)
 

# Запуск бота
async def main():
    # обновляем структуру базы данных
    await sql_mgt.create_db()

    #bot = Bot(token=TELEGRAM_BOT_TOKEN)
    #dp = Dispatcher()
    await sql_mgt.upload_admins(global_objects.admin_list)
    admins_dict = await sql_mgt.get_admins_id()

    global_objects.admin_list = [admin[0] for admin in admins_dict]
    #dp.include_routers(questions.router, different_types.router)

    path_directory = os.path.dirname(os.path.abspath(__file__))
    with open(path_directory + '/pyment_bot_dir/pyment_bot_settings.json', 'r') as f:
        pytment_bot_settings = json.load(f)

    global_objects.pyment_bot_settings = pytment_bot_settings

    # Альтернативный вариант регистрации роутеров по одному на строку
    await init_other_object(commands)
    await init_other_object(confirm_age_phone)
    await init_other_object(answer_button_menu)
    await init_other_object(text_heandler)
    await init_other_object(media_heandler)
    await init_other_object(import_files)
    await init_other_object(admin_answer_button)
    await init_other_object(answer_button_settings)
    await init_other_object(answer_button_subscription)
    await init_other_object(pyments)
    await init_other_object(order)
    await sql_mgt.init_wallet()

    global_objects.bot.session.middleware(RequestLogger(ignore=[GetUpdates]))
    #global_objects.bot.session.middleware(IncomingLogger())
    global_objects.dp.update.middleware(IncomingLogger())
    #global_objects.dp.message.middleware(LoggingMiddleware())
    #global_objects.dp.callback_query.middleware(LoggingMiddleware())
    global_objects.dp.update.middleware(LoggingMiddleware())

    # раз в день рестартим бота по времени из настройки
    hour = global_objects.settings_bot['bot_settings']['restart']['hour']
    minet = global_objects.settings_bot['bot_settings']['restart']['minet']
    set_restart(hour=hour, minet=minet)

    # запускаем процесс, который будет удалять старые заказы
    run_order_delete_process()

    # проверяем, не пора ли платить
    #await pyments.monthly_payment()

    monthly_payment_with_conn(global_objects.settings_bot.get('run_directory'))


    # Запускаем бота и пропускаем все накопленные входящие
    # Да, этот метод можно вызвать даже если у вас поллинг
    #await bot.delete_webhook(drop_pending_updates=True)
    await global_objects.dp.start_polling(global_objects.bot)


def run_bot(telegram_bot_token:str, admin_id_list:list, command_dict:dict, settings_bot:dict):
    global global_objects

    create_folder('./load_files')

    # подгружаем основной файл, если его ещё нету
    copy_or_rename_file('', './load_files', 'tree_data.json', 'data_tree.json')

    bot = Bot(telegram_bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    admin_list = admin_id_list
    tree_data = Tree_data(MAIN_JSON_FILE)

    global_objects = GlobalObjects(tree_data, bot, admin_list, dp, command_dict, settings_bot)

    sql_mgt.init_object(global_objects)

    # создаём файл бд, если он ещё не создан
    sql_mgt.create_db_file()

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())


if __name__ == "__main__":
    run_bot()
    
