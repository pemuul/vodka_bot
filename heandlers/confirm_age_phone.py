from __future__ import annotations
from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    Update,
    BotCommandScopeDefault,
    FSInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    PhotoSize,
    Document,
    Audio,
    Video,
    Voice,
    VideoNote,
    Sticker,
    Animation,
)
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

REG_STAGE_FLOW = ["start", "phone", "age", "privacy", "name", "done"]
REG_PREVIOUS_STAGE = {
    stage: REG_STAGE_FLOW[index - 1] if index > 0 else None
    for index, stage in enumerate(REG_STAGE_FLOW)
}
BACK_TEXT_TRIGGERS = ("назад", "вернут")


def _normalize_text(value: str | None) -> str:
    return value.strip().lower() if value else ""


async def set_registration_stage(user_id: int, stage: str) -> None:
    current = await sql_mgt.get_param(user_id, "REG_STAGE")
    if current == stage:
        return

    await sql_mgt.set_param(user_id, "REG_STAGE", stage)
    prev_stage = REG_PREVIOUS_STAGE.get(stage)
    await sql_mgt.set_param(user_id, "REG_PREV_STAGE", prev_stage or "")


async def revert_registration_stage(user_id: int) -> str | None:
    prev_stage = await sql_mgt.get_param(user_id, "REG_PREV_STAGE")
    if not prev_stage:
        return None

    await set_registration_stage(user_id, prev_stage)
    return prev_stage


def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    global_objects.dp.message.outer_middleware(RegistrationMiddleware())
    #global_objects.dp.update.middleware.register(SaveIncomingFiles())
    menu.init_object(global_objects)
    sql_mgt.init_object(global_objects)
    settings_bot.init_object(global_objects)
    commands.init_object(global_objects)


class RegistrationMiddleware(BaseMiddleware):
    """Пошаговая проверка регистрации пользователя."""

    async def __call__(self, handler, event: Message, data: dict) -> Any:
        await commands.delete_answer_messages(event)

        user = await sql_mgt.get_user_async(event.chat.id)
        if not user:
            await sql_mgt.insert_user(event)
            user = await sql_mgt.get_user_async(event.chat.id)

        stage = await sql_mgt.get_param(event.chat.id, "REG_STAGE")
        if not stage:
            await set_registration_stage(event.chat.id, "start")
            stage = "start"

        if stage != "done":
            normalized_text = _normalize_text(event.text)
            if normalized_text and any(trigger in normalized_text for trigger in BACK_TEXT_TRIGGERS):
                reverted = await revert_registration_stage(event.chat.id)
                if reverted:
                    stage = reverted

            if stage == "start":
                await set_registration_stage(event.chat.id, "start")
                await send_greeting(event)
                await commands.delete_this_message(event)
                return

            if stage == "phone":
                if event.contact:
                    return await handler(event, data)
                await send_phone_request(event)
                await commands.delete_this_message(event)
                return

            if stage == "age":
                await send_age_question(event)
                await commands.delete_this_message(event)
                return

            if stage == "privacy":
                await send_privacy_policy(event)
                await commands.delete_this_message(event)
                return

            if stage == "name":
                if normalized_text and any(trigger in normalized_text for trigger in BACK_TEXT_TRIGGERS):
                    stage = await sql_mgt.get_param(event.chat.id, "REG_STAGE")
                    if stage == "name":
                        await send_name_request(event)
                        await commands.delete_this_message(event)
                        return
                if not event.text:
                    await send_name_request(event)
                    await commands.delete_this_message(event)
                    return
                await sql_mgt.update_user_async(event.from_user.id, {"name": event.text})
                await set_registration_stage(event.from_user.id, "done")
                answer_message = await event.answer(f"Очень приятно, {event.text}!")
                await commands.delete_answer_leater(answer_message)
                await sql_mgt.set_param(event.chat.id, "DELETE_LAST_MESSAGE", "yes")
                await commands.delete_this_message(event)
                await commands.command_start_handler(event)
                return
        return await handler(event, data)


async def send_greeting(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Продолжить", callback_data="reg_continue")]]
    )
    answer_message = await message.answer(
        "Добро пожаловать в «Клуб любителей FINSKY ICE» 💙 Здесь вы найдете аппетитные рецепты коктейлей, первыми узнаете о новинках и сможете выиграть призы за участие в акциях 🎁 Присоединяйтесь! 🚀",
        reply_markup=kb,
    )
    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, "DELETE_LAST_MESSAGE", "yes")


async def send_phone_request(message: Message):
    reply_kb_contact = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    answer_message = await message.answer(
        "Поделитесь вашим контактным номером телефона для нашей службы поддержки ⬇️",
        reply_markup=reply_kb_contact,
    )
    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, "DELETE_LAST_MESSAGE", "yes")


async def send_age_question(message: Message):
    inline_kb_age = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Мне есть 18 лет", callback_data="age_yes"),
                InlineKeyboardButton(text="Мне нет 18 лет", callback_data="age_no"),
            ]
        ]
    )
    answer_message = await message.answer(
        "По правилам нашего Клуба вам должно быть больше 18 лет. Вы уже достигли совершеннолетия? ✨",
        reply_markup=inline_kb_age,
    )
    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, "DELETE_LAST_MESSAGE", "yes")


async def send_privacy_policy(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я даю согласие", callback_data="privacy_yes")],
            [InlineKeyboardButton(text="Я не даю согласие", callback_data="privacy_no")],
        ]
    )
    answer_message = await message.answer(
        "Продолжая использовать чат-бот, вы соглашаетесь с политикой конфиденциальности",
        reply_markup=kb,
    )
    await commands.delete_answer_leater(answer_message)

    file_path = await sql_mgt.get_param(0, "privacy_policy_file")
    if file_path:
        local = Path(__file__).resolve().parent.parent / "site_bot" / file_path.lstrip("/")
        if local.exists():
            ext = local.suffix
            await message.answer_document(
                FSInputFile(local, filename=f"Политика конфиденциальности{ext}"),
                caption="Политика конфиденциальности",
            )
    await sql_mgt.set_param(message.chat.id, "DELETE_LAST_MESSAGE", "yes")


async def send_name_request(message: Message):
    answer_message = await message.answer("Как я могу к вам обращаться? 💙")
    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, "DELETE_LAST_MESSAGE", "yes")


@router.callback_query(F.data == "reg_continue")
async def reg_continue_handler(call: CallbackQuery):
    await set_registration_stage(call.from_user.id, "phone")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await commands.delete_this_message(call.message)
    await send_phone_request(call.message)
    await call.answer()


@router.callback_query(F.data == "age_yes")
async def age_yes_handler(call: CallbackQuery):
    await sql_mgt.update_user_async(call.from_user.id, {"age_18": True})
    await set_registration_stage(call.from_user.id, "privacy")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await commands.delete_this_message(call.message)
    await send_privacy_policy(call.message)
    await call.answer()


@router.callback_query(F.data == "age_no")
async def age_no_handler(call: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Вернуться", callback_data="age_retry")]]
    )
    await set_registration_stage(call.from_user.id, "age")
    await call.message.edit_text(
        "Обязательно возвращайтесь, когда вам исполнится 18 лет. До новых встреч! 👋",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data == "age_retry")
async def age_retry_handler(call: CallbackQuery):
    await set_registration_stage(call.from_user.id, "age")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await commands.delete_this_message(call.message, force=True)
    await send_age_question(call.message)
    await call.answer()


@router.callback_query(F.data == "privacy_yes")
async def privacy_yes_handler(call: CallbackQuery):
    await sql_mgt.set_param(call.from_user.id, "policy_agreed", "yes")
    await set_registration_stage(call.from_user.id, "name")
    try:
        await commands.delete_message_by_id(call.message.chat.id, call.message.message_id - 1)
    except Exception:
        pass
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await commands.delete_this_message(call.message)
    await send_name_request(call.message)
    await call.answer()


@router.callback_query(F.data == "privacy_no")
async def privacy_no_handler(call: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Вернуться", callback_data="privacy_retry")]]
    )
    try:
        await commands.delete_message_by_id(call.message.chat.id, call.message.message_id - 1)
    except Exception:
        pass
    await set_registration_stage(call.from_user.id, "privacy")
    await call.message.edit_text(
        "Обязательно возвращайтесь, если передумаете. До новых встреч! 👋",
        reply_markup=kb,
    )
    await call.answer()


@router.callback_query(F.data == "privacy_retry")
async def privacy_retry_handler(call: CallbackQuery):
    await set_registration_stage(call.from_user.id, "privacy")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await commands.delete_this_message(call.message, force=True)
    await send_privacy_policy(call.message)
    await call.answer()


@router.message(F.contact)
async def contact_handler(message: Message):
    phone_number = message.contact.phone_number
    await sql_mgt.update_user_async(message.from_user.id, {"phone": phone_number})
    await set_registration_stage(message.from_user.id, "age")
    answer_message = await message.answer(
        "Спасибо! Ваш номер сохранён.", reply_markup=ReplyKeyboardRemove()
    )
    await commands.delete_answer_leater(answer_message)
    await sql_mgt.set_param(message.chat.id, "DELETE_LAST_MESSAGE", "yes")
    await commands.delete_this_message(message)
    await send_age_question(message)


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

