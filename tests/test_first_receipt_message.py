"""Tests for the first-receipt reply in heandlers/media_heandler.py (set_photo).

Первый чек пользователя в акции отвечает приветствием, подписью к PDF-каталогу. Заголовок
жирный, и сделано это через entities, а не HTML-тегами: outgoing_logger.RequestLogger пишет
caption в participant_messages как есть, а админ-панель показывает его через textContent —
теги были бы видны там сырыми.

Requires pyzbar (native zbar) — same DYLD_LIBRARY_PATH requirement as
test_media_heandler_guaranteed_prize.py, see CLAUDE.md.
"""

import asyncio
import io
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.methods import SendDocument, SendMessage
from aiogram.utils.text_decorations import html_decoration

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sql_mgt
from heandlers import media_heandler

CHAT_ID = 4242
TITLE = "Держите подарок — электронный каталог коктейлей FINSKY ICE!"
EXPECTED_HTML = (
    f"🎁 <b>{TITLE}</b>\n"
    "Загружайте чеки, соответствующие условиям акции, и участвуйте в розыгрыше призов.\n"
    "Чем больше принятых чеков — тем больше шансов на победу!\n"
    "Хотите загрузить ещё чек?"
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestFirstReceiptMessageContent:
    def test_text_has_no_markup_and_parse_mode_is_off(self):
        kwargs = media_heandler.FIRST_RECEIPT_MESSAGE.as_kwargs()
        assert "<" not in kwargs["text"] and ">" not in kwargs["text"]
        # parse_mode=None перекрывает HTML по умолчанию у Bot: при заданных entities
        # Telegram не должен разбирать текст второй раз
        assert kwargs["parse_mode"] is None

    def test_only_the_title_is_bold(self):
        kwargs = media_heandler.FIRST_RECEIPT_MESSAGE.as_kwargs()
        [entity] = kwargs["entities"]
        assert entity.type == "bold"
        # Смещения в UTF-16: смайлик 🎁 занимает два code unit-а, плюс пробел
        assert entity.offset == 3
        assert entity.length == len(TITLE.encode("utf-16-le")) // 2
        assert html_decoration.unparse(kwargs["text"], kwargs["entities"]) == EXPECTED_HTML

    def test_fits_telegram_caption_limit(self):
        # тот же текст уходит подписью к документу, а у подписи лимит 1024 символа
        assert len(media_heandler.FIRST_RECEIPT_MESSAGE.as_kwargs()["text"]) <= 1024

    def test_request_logger_sees_plain_text(self):
        """RequestLogger берёт method.text / method.caption — там не должно быть тегов."""
        plain = media_heandler.FIRST_RECEIPT_MESSAGE.as_kwargs()["text"]
        as_message = SendMessage(
            chat_id=CHAT_ID, **media_heandler.FIRST_RECEIPT_MESSAGE.as_kwargs()
        )
        as_document = SendDocument(
            chat_id=CHAT_ID,
            document="file-id",
            **media_heandler.FIRST_RECEIPT_MESSAGE.as_kwargs(
                text_key="caption", entities_key="caption_entities"
            ),
        )
        assert as_message.text == plain
        assert as_document.caption == plain


def _message():
    message = MagicMock()
    message.chat.id = CHAT_ID
    message.message_id = 10
    message.photo = [MagicMock(file_id="photo-file-id")]
    message.reply = AsyncMock()
    message.reply_document = AsyncMock()
    return message


@pytest.fixture()
def photo_flow(tmp_db, tmp_path, monkeypatch):
    """Окружение для set_photo(): реальная SQLite с активным этапом, бот-заглушка."""
    fake_go = MagicMock()
    fake_go.bot.download = AsyncMock(return_value=io.BytesIO(b"jpeg"))
    monkeypatch.setattr(media_heandler, "global_objects", fake_go)
    # фото чека не должно попадать в site_bot/static/uploads репозитория
    monkeypatch.setattr(media_heandler, "UPLOAD_DIR_CHECKS", tmp_path)

    conn = sqlite3.connect(tmp_db)
    try:
        draw_id = conn.execute("INSERT INTO prize_draws (title) VALUES ('Акция')").lastrowid
        conn.execute(
            "INSERT INTO prize_draw_stages (draw_id, name, stage_type, status) "
            "VALUES (?, 'Этап', 'standard', 'active')",
            (draw_id,),
        )
        conn.commit()
    finally:
        conn.close()
    run(sql_mgt.set_param(CHAT_ID, "GET_CHECK", str(True)))
    return tmp_path


def _set_catalog(tmp_path):
    pdf = tmp_path / "catalog.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    # set_photo() клеит CATALOG_FILE с site_bot/ — относительный путь выводит ровно на tmp-файл
    site_dir = Path(media_heandler.__file__).resolve().parent.parent / "site_bot"
    run(sql_mgt.set_param(0, "CATALOG_FILE", os.path.relpath(pdf, site_dir)))


class TestSetPhotoFirstReceiptReply:
    def test_without_catalog_replies_with_bold_title(self, photo_flow):
        message = _message()
        run(media_heandler.set_photo(message))

        message.reply.assert_awaited_once()
        message.reply_document.assert_not_awaited()
        assert message.reply.await_args.args == ()
        kwargs = message.reply.await_args.kwargs
        assert kwargs["parse_mode"] is None
        assert html_decoration.unparse(kwargs["text"], kwargs["entities"]) == EXPECTED_HTML

    def test_with_catalog_sends_it_with_bold_caption(self, photo_flow):
        _set_catalog(photo_flow)
        message = _message()
        run(media_heandler.set_photo(message))

        message.reply_document.assert_awaited_once()
        message.reply.assert_not_awaited()
        kwargs = message.reply_document.await_args.kwargs
        assert kwargs["parse_mode"] is None
        assert (
            html_decoration.unparse(kwargs["caption"], kwargs["caption_entities"])
            == EXPECTED_HTML
        )

    def test_greeting_is_sent_only_for_the_first_receipt(self, photo_flow):
        _set_catalog(photo_flow)
        run(media_heandler.set_photo(_message()))

        second = _message()
        run(media_heandler.set_photo(second))

        second.reply_document.assert_not_awaited()
        second.reply.assert_awaited_once()
        assert second.reply.await_args.args[0].startswith(
            "Чек загружен и находится в статусе Проверка"
        )
