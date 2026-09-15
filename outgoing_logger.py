"""Логирование исходящих сообщений бота в participant_messages.

Раньше этот middleware жил в bot.py и навешивался только на Bot процесса бота. Чеки при этом
обрабатывает отдельный процесс (receipt_queue_worker.py) со своим экземпляром Bot — и все его
ответы («✅ Чек подтверждён», «❌ В чеке не найден нужный товар», сообщения о прогрессе) уходили
пользователю, но не попадали в историю переписки. В админ-панели чат участника выглядел так,
будто бот ему вообще не отвечал: человек загружает пять чеков, видны только «Чек загружен и
находится в статусе Проверка», а пяти подтверждений нет. Отсюда и родилась жалоба «юзерам
перестали идти сообщения».

Поэтому модуль общий: его подключают и бот, и воркер очереди.

Два отличия от прежней версии:

1. Запись делается ПОСЛЕ успешной отправки, а не до. Так в истории оказывается только то, что
   Telegram действительно принял, и становится доступен message_id ответа.
2. Сохраняется telegram-идентификатор отправленного сообщения (`tg_message_id`), чтобы
   сообщение можно было потом изменить или удалить. Дополнительно, если отправка идёт в
   контексте конкретного чека (`receipt_message_context`), сохраняется ссылка на него.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Type

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, InputMedia, ReplyKeyboardMarkup

import sql_mgt

logger = logging.getLogger(__name__)

# Последняя reply-клавиатура, отправленная пользователю: по ней входящий текст опознаётся как
# нажатие кнопки, а не как обычное сообщение (используется в bot.py: IncomingLogger).
last_reply_keyboard: Dict[int, List[str]] = {}

# Чек, в контексте которого сейчас отправляется сообщение. Нужен, чтобы связать отправленное
# сообщение с чеком и потом иметь возможность его удалить/изменить — например, убрать неверный
# ответ, когда администратор поменял статус чека.
_current_receipt_id: ContextVar[Optional[int]] = ContextVar(
    "current_receipt_id", default=None
)


@contextmanager
def receipt_message_context(receipt_id: Optional[int]):
    """Пометить все сообщения, отправленные внутри блока, ссылкой на чек."""
    token = _current_receipt_id.set(receipt_id)
    try:
        yield
    finally:
        _current_receipt_id.reset(token)


def _extract_buttons(method: TelegramMethod[Any], chat_id: int) -> List[Dict[str, Any]]:
    buttons: List[Dict[str, Any]] = []
    markup = getattr(method, "reply_markup", None)
    if isinstance(markup, InlineKeyboardMarkup):
        for row in markup.inline_keyboard:
            for btn in row:
                buttons.append(
                    {
                        "text": btn.text,
                        "callback_data": getattr(btn, "callback_data", None),
                        "url": getattr(btn, "url", None),
                        "web_app_url": getattr(getattr(btn, "web_app", None), "url", None),
                    }
                )
        # inline-клавиатура не заменяет reply, поэтому прошлую забываем
        last_reply_keyboard.pop(chat_id, None)
    elif isinstance(markup, ReplyKeyboardMarkup):
        btn_texts: List[str] = []
        for row in markup.keyboard:
            for btn in row:
                btn_info: Dict[str, Any] = {"text": btn.text}
                if btn.request_contact:
                    btn_info["request_contact"] = True
                if btn.request_location:
                    btn_info["request_location"] = True
                if btn.web_app:
                    btn_info["web_app_url"] = btn.web_app.url
                buttons.append(btn_info)
                btn_texts.append(btn.text)
        if btn_texts:
            last_reply_keyboard[chat_id] = btn_texts
    else:
        last_reply_keyboard.pop(chat_id, None)
    return buttons


def _extract_media(method: TelegramMethod[Any]) -> List[Dict[str, Any]]:
    media_list: List[Dict[str, Any]] = []
    media = getattr(method, "media", None)
    items = media if isinstance(media, list) else [media] if media else []
    for m in items:
        if isinstance(m, InputMedia):
            media_list.append(
                {
                    "type": m.type.value if hasattr(m.type, "value") else m.type,
                    "media": m.media,
                    "caption": m.caption,
                }
            )
    return media_list


def _extract_sent_message_id(result: Any) -> Optional[int]:
    """message_id отправленного сообщения. Для медиагруппы берём первое из списка."""
    if isinstance(result, (list, tuple)):
        result = result[0] if result else None
    message_id = getattr(result, "message_id", None)
    return int(message_id) if isinstance(message_id, int) else None


class RequestLogger(BaseRequestMiddleware):
    """Пишет в participant_messages всё, что бот отправил пользователю."""

    def __init__(self, ignore: Optional[List[Type[TelegramMethod[Any]]]] = None):
        self.ignore = ignore or []

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType,
        bot: Bot,
        method: TelegramMethod[Any],
        *args,
        **kwargs,
    ) -> Any:
        chat_id = getattr(method, "chat_id", None)
        loggable = type(method) not in self.ignore and chat_id is not None

        buttons: List[Dict[str, Any]] = []
        media_list: List[Dict[str, Any]] = []
        text: Optional[str] = None
        if loggable:
            # caption — текст сообщения с вложением (документ, фото). Раньше учитывался только
            # text, поэтому, например, каталог с подписью-поздравлением после первого чека в
            # историю не попадал вовсе.
            text = getattr(method, "text", None) or getattr(method, "caption", None)
            if text:
                buttons = _extract_buttons(method, chat_id)
                media_list = _extract_media(method)
            else:
                loggable = False

        result = await make_request(bot, method, *args, **kwargs)

        if loggable:
            try:
                await sql_mgt.add_participant_message(
                    user_tg_id=chat_id,
                    sender="admin",
                    text=text,
                    buttons=buttons or None,
                    media=media_list or None,
                    tg_message_id=_extract_sent_message_id(result),
                    receipt_id=_current_receipt_id.get(),
                )
            except Exception:
                # История переписки — вспомогательная вещь: если её не удалось записать, это не
                # повод считать отправку неуспешной и уводить чек в повторную обработку.
                logger.exception(
                    "Не удалось записать исходящее сообщение для chat_id=%s", chat_id
                )

        return result
