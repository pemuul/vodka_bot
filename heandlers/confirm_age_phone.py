from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update, BotCommandScopeDefault, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, PhotoSize, Document, Audio, Video, Voice, VideoNote, Sticker, Animation
from aiogram.enums import ParseMode
import os
import sys
import json
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any, Union, Type

from heandlers import menu, pyments, web_market, settings_bot, commands
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
    global_objects.dp.message.outer_middleware(AgePhoneCheckMiddleware())
    #global_objects.dp.update.middleware.register(SaveIncomingFiles())
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)
    settings_bot.init_object(global_objects)
    commands.init_object(global_objects)

class AgePhoneCheckMiddleware(BaseMiddleware):
    """
    Перехватывает абсолютно все Message (outer), проверяет:
      1) Если поле age_18=False → блокирует и отправляет inline-кнопку “Мне есть 18 лет”.
      2) Если age_18=True, но phone=None → блокирует и отправляет Reply-кнопку “Отправить номер телефона”.
      3) Если пришёл Message с contact → пропускает его дальше, чтобы сработал хендлер @router.message(F.contact).
      4) Как только оба поля в базе (age_18 и phone) заполнены → пропускает любые другие сообщения к обычным хендлерам.
    """

    async def __call__(self, handler, event: Message, data: dict) -> any:
        # 1) Если пришёл контакт – пропускаем дальше (должен сработать хендлер @router.message(F.contact))
        await commands.delete_answer_messages(event)

        if event.contact:
            return await handler(event, data)

        # 2) Получаем или создаём запись пользователя в БД
        user = await sql_mgt.get_user_async(event.chat.id)
        if not user:
            await sql_mgt.insert_user(event)
            user = await sql_mgt.get_user_async(event.chat.id)

        # 3) Проверка возраста
        if not user.get("age_18", False):
            inline_kb_age = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Мне есть 18 лет",
                            callback_data="confirm_age"
                        )
                    ]
                ]
            )
            answer_message = await event.answer(
                "Прежде чем продолжить, подтвердите, что вам есть 18 лет:\n\n"
                "Нажмите кнопку ниже.",
                reply_markup=inline_kb_age
            )

            await commands.delete_answer_leater(answer_message)
            await sql_mgt.set_param(event.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
            await commands.delete_this_message(event)
            return  # НЕ вызываем handler(event, data) – блокируем все остальные сообщения

        # 4) Проверка наличия телефона
        if not user.get("phone"):
            # Отправляем ReplyKeyboard с одной кнопкой request_contact (один шаг отправки контакта)
            await send_phone_request(event)
            return  # Снова блокируем всё, кроме нажатия этой кнопки

        # 5) Оба условия выполнены – пускаем Message дальше к соответствующим хендлерам
        return await handler(event, data)
    

async def send_phone_request(message: Message):
    """
    Отправляет ReplyKeyboard с кнопкой “Отправить номер телефона” (request_contact=True).
    Используется в хендлере @router.callback_query(F.data == "start_phone_share").
    """
    reply_kb_contact = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Отправить номер телефона",
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    answer_message = await message.answer(
        "Чтобы продолжить работу с ботом, необходимо поделиться номером телефона.\n\n"
        "Нажмите кнопку ниже, чтобы отправить контакт:",
        reply_markup=reply_kb_contact
    )

    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')
    await commands.delete_this_message(message)


# ----------------------
# 2. CallbackQuery-хендлер: подтверждение возраста
# ----------------------
@router.callback_query(F.data == "confirm_age")
async def confirm_age_handler(call: CallbackQuery):
    """
    Когда пользователь нажал “Мне есть 18 лет”:
      – сохраняем age_18=True в БД,
      – редактируем исходное сообщение, убирая inline-кнопку.
    """
    await sql_mgt.update_user_async(call.from_user.id, {"age_18": True})
    await call.answer("Возраст подтверждён", show_alert=False)

    # Убираем inline-кнопку и меняем текст
    try:
        await call.message.edit_text("✅ Вы подтвердили, что вам есть 18 лет.")
        await send_phone_request(call.message)
    except:
        pass  # Если редактирование не удалось, просто продолжаем


# ----------------------
# 3. Message-хендлер: получение контакта (content_type=contact)
# ----------------------
@router.message(F.contact)
async def contact_handler(message: Message):
    """
    Когда пользователь нажимает кнопку “Отправить номер телефона” (ReplyKeyboardMarkup → request_contact),
    Telegram присылает Message.contact. Сохраняем phone в БД и убираем клавиатуру.
    """

    phone_number = message.contact.phone_number
    await sql_mgt.update_user_async(message.from_user.id, {"phone": phone_number})

    # Убираем клавиатуру, возвращаем обычную (или пустую) клавиатуру
    answer_message = await message.answer(
        "Спасибо! Ваш номер сохранён."
    )
    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')


    await commands.command_start_handler(message)


FILES_DIR = Path("files")

class SaveIncomingFiles(BaseMiddleware):
    # было: base_dir: str | Path
    def __init__(self, base_dir: Union[str, Path] = "files") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any]
    ):
        if event.message:                       # работаем только с Message-update
            bot: Bot = data["bot"]
            await self._save_attachments(bot, event.message)

        return await handler(event, data)

    # ---------- внутренние методы ---------- #
    async def _save_attachments(self, bot: Bot, m: Message) -> None:
        """
        Перебираем все возможные типы вложений и сохраняем.
        """
        # 📷 Фото — берём самое большое
        if m.photo:
            await self._dl(bot, m.photo[-1], ".jpg")

        # 📄 Документ
        if m.document:
            await self._dl(bot, m.document, Path(m.document.file_name or ".bin").suffix)

        # 🎵 Аудио
        if m.audio:
            await self._dl(bot, m.audio, Path(m.audio.file_name or ".mp3").suffix)

        # 🎞️ Видео
        if m.video:
            await self._dl(bot, m.video, Path(m.video.file_name or ".mp4").suffix)

        # 🎙 Голос
        if m.voice:
            await self._dl(bot, m.voice, ".ogg")

        # 💬 Видео-нота
        if m.video_note:
            await self._dl(bot, m.video_note, ".mp4")

        # 🦄 Стикер (обычный/анимированный)
        if m.sticker:
            # *.webp, *.tgs или *.webm в зависимости от формата
            ext = {
                "regular": ".webp",
                "video": ".webm",
                "animated": ".tgs",
            }.get(m.sticker.format.value, ".dat")
            await self._dl(bot, m.sticker, ext)

        # 🎞 GIF-анимация
        if m.animation:
            await self._dl(bot, m.animation, Path(m.animation.file_name or ".gif").suffix)

    async def _dl(self, bot: Bot, obj, default_ext: str) -> None:
        """
        Унифицированная загрузка любого Downloadable-объекта.
        Имя файла строим так: <file_id><расширение>.
        """
        # file_id подходит под FAT-32 (буквы/цифры/«_»), поэтому безопасен
        filename = f"{obj.file_id}{default_ext}"
        await bot.download(obj, destination=self.base_dir / filename)