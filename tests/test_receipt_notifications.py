"""Тесты на ответы пользователю по чеку и на сопутствующие им механизмы.

Покрывают то, что раньше не было покрыто ничем и из-за чего на проде появилась жалоба
«юзерам перестали идти сообщения»:

* чек, ушедший к администратору («На ручной проверке», «Ошибка»), не попадал в ленту
  уведомлений и повисал до тех пор, пока его случайно не заметят в списке (пользователю в
  этих статусах намеренно не пишут — решение владельца, CLAUDE.md п. 14);
* при min_quantity == 1 исход «условия выполнены» наступал сразу и не слал настроенный в
  панели текст, то есть этот текст не отправлялся никогда;
* «Чек принят» уходило вместе с «0 попыток выиграть»;
* пустой остаток оставлял в тексте заголовок без содержимого;
* этапы не переключались по датам, из-за чего акция останавливалась молча;
* ответы бота не сохраняли telegram-id и их нельзя было потом удалить.

Требует pyzbar (нативный zbar) — тот же DYLD_LIBRARY_PATH, что и у соседних тестов, см.
CLAUDE.md.
"""

import asyncio
import datetime
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import receipt_validation
import sql_mgt
from heandlers import media_heandler


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def mem_db(monkeypatch):
    schema_path = Path(__file__).resolve().parents[1] / "table_shem.json"
    with open(schema_path) as fh:
        schema = json.load(fh)

    db_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    db_file.close()

    conn = sqlite3.connect(db_file.name)
    for ddl in schema.values():
        conn.execute("CREATE TABLE IF NOT EXISTS " + ddl)
    conn.commit()
    conn.close()

    original = sql_mgt.db_name
    monkeypatch.setattr(sql_mgt, "db_name", db_file.name)
    yield db_file.name
    monkeypatch.setattr(sql_mgt, "db_name", original)
    os.unlink(db_file.name)


def _insert_draw(db_path, title="Test draw"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("INSERT INTO prize_draws (title) VALUES (?)", (title,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_stage(
    db_path, draw_id, name="Этап", stage_type="standard", status="upcoming",
    start_date=None, end_date=None, progress_message_text=None,
):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_stages "
            "(draw_id, name, stage_type, status, start_date, end_date, progress_message_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (draw_id, name, stage_type, status, start_date, end_date, progress_message_text),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_rule(db_path, stage_id, title="Rule", aliases="finsky", min_quantity=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_rules (stage_id, title, aliases, min_quantity, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            (stage_id, title, aliases, min_quantity),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


class _FakeGlobalObjects:
    def __init__(self):
        self.ocr_pool = None
        self.bot = AsyncMock()


def _fns_qr(n: int) -> str:
    return f"t=20250412T1942&s=100.00&fn=1&i={n}&fp=3&n=1"


def _mock_qr_and_fns(monkeypatch, qr_value, items):
    monkeypatch.setattr(media_heandler, "_detect_qr", lambda path: qr_value)
    monkeypatch.setattr(
        media_heandler, "get_receipt_by_qr", lambda qr: ({"items": items}, None)
    )


def _sent_text(fake_go):
    return fake_go.bot.send_message.call_args.args[1]


# ---------------------------------------------------------------------------
# Единый список «статус → текст»
# ---------------------------------------------------------------------------

class TestStatusMessages:
    def test_every_final_status_is_decided(self):
        """У каждого финального статуса либо есть текст, либо он явно помечен «молчим».
        Третьего быть не должно: статус, про который забыли, — это молча потерянный ответ."""
        for status in receipt_validation.FINAL_RECEIPT_STATUSES:
            message = receipt_validation.build_status_message(status)
            silent = receipt_validation.is_silent_status(status)
            assert bool(message) != silent, f"статус {status!r} не определён однозначно"
            if message:
                assert message.strip() == message

    def test_manual_review_stays_silent(self):
        """Решение владельца (CLAUDE.md, «Поток обработки чека», п. 14): чек, ушедший на
        ручную проверку, НЕ пишет пользователю ничего — ответ придёт, когда администратор
        примет решение."""
        assert receipt_validation.build_status_message("На ручной проверке") is None
        assert receipt_validation.is_silent_status("На ручной проверке") is True

    def test_error_status_stays_silent(self):
        assert receipt_validation.build_status_message("Ошибка") is None
        assert receipt_validation.is_silent_status("Ошибка") is True

    def test_answered_statuses_are_not_silent(self):
        for status in ("Подтверждён", "Чек уже загружен", "Нет товара в чеке"):
            assert receipt_validation.is_silent_status(status) is False

    def test_unknown_status_returns_none(self):
        assert receipt_validation.build_status_message("Неизвестно") is None
        assert receipt_validation.build_status_message(None) is None

    def test_in_progress_status_has_no_final_text(self):
        """«В авто обработке» — промежуточное состояние, ответ придёт позже."""
        assert "В авто обработке" not in receipt_validation.FINAL_RECEIPT_STATUSES


# ---------------------------------------------------------------------------
# Подстановка в шаблоны
# ---------------------------------------------------------------------------

class TestFillPlaceholder:
    def test_substitutes_value(self):
        assert receipt_validation.fill_placeholder("а {x} б", "x", "1") == "а 1 б"

    def test_empty_value_drops_line_and_its_heading(self):
        """Заголовок без содержимого — то самое «пустое место» в сообщении."""
        template = "Чек принят\n\nОсталось докупить:\n{remaining_items}\n\nХвост"
        result = receipt_validation.fill_placeholder(template, "remaining_items", "")
        assert "Осталось докупить" not in result
        assert result == "Чек принят\n\nХвост"

    def test_empty_value_does_not_leave_blank_runs(self):
        template = "А:\n{x}\n\n\nБ"
        assert "\n\n\n" not in receipt_validation.fill_placeholder(template, "x", "")

    def test_missing_placeholder_is_noop(self):
        assert receipt_validation.fill_placeholder("текст", "x", "") == "текст"


class TestRenderedTemplatesAreClean:
    """Ни один шаблон не должен уйти пользователю с остатками разметки."""

    @pytest.mark.parametrize("entries", [0, 1, 5])
    @pytest.mark.parametrize("remaining", ["", "• «Товар» — ещё 1 шт."])
    def test_standard_progress_message_is_clean(self, remaining, entries):
        text = receipt_validation.build_standard_progress_message(None, remaining, entries)
        assert "{" not in text and "}" not in text
        assert "\n\n\n" not in text
        assert text.strip() == text

    @pytest.mark.parametrize("remaining", ["", "• «Товар» — ещё 2 шт."])
    def test_guaranteed_progress_message_is_clean(self, remaining):
        text = receipt_validation.build_progress_message(None, remaining)
        assert "{" not in text and "}" not in text
        assert "\n\n\n" not in text

    def test_custom_template_without_remaining_placeholder(self):
        """Шаблон владельца с прода — только счётчик попыток, без остатка."""
        template = "Чек принят ✅\n\nСейчас у вас {entries_count} 🎟️"
        text = receipt_validation.build_standard_progress_message(template, "", 2)
        assert text == "Чек принят ✅\n\nСейчас у вас 2 попытки выиграть 🎟️"


# ---------------------------------------------------------------------------
# Защита от взаимоисключающего текста
# ---------------------------------------------------------------------------

class TestContradictoryAcceptance:
    def test_confirmed_with_zero_progress_is_contradiction(self):
        """Ровно то, что ушло человеку 14.09.2026: чек засчитан, а прогресс нулевой."""
        progress = [{"id": 1, "title": "HARD TEA", "min_quantity": 1, "progress": 0.0}]
        assert receipt_validation.is_contradictory_acceptance("Подтверждён", progress) is True

    def test_partial_progress_is_legitimate(self):
        """0 попыток при частично собранном комплекте — честный текст, не противоречие."""
        progress = [{"id": 1, "title": "Ром", "min_quantity": 3, "progress": 2.0}]
        assert receipt_validation.is_contradictory_acceptance("Подтверждён", progress) is False
        assert receipt_validation.compute_entries_count(progress) == 0

    def test_other_statuses_are_not_checked(self):
        progress = [{"id": 1, "title": "X", "min_quantity": 1, "progress": 0.0}]
        assert receipt_validation.is_contradictory_acceptance("Нет товара в чеке", progress) is False

    def test_no_rules_is_not_contradiction(self):
        assert receipt_validation.is_contradictory_acceptance("Подтверждён", []) is False
        assert receipt_validation.is_contradictory_acceptance("Подтверждён", None) is False

    def test_partially_zero_is_not_contradiction(self):
        """Часть правил закрыта, часть нет — чек внёс вклад, текст корректен."""
        progress = [
            {"id": 1, "title": "A", "min_quantity": 1, "progress": 1.0},
            {"id": 2, "title": "B", "min_quantity": 1, "progress": 0.0},
        ]
        assert receipt_validation.is_contradictory_acceptance("Подтверждён", progress) is False


# ---------------------------------------------------------------------------
# Количество позиции по умолчанию
# ---------------------------------------------------------------------------

class TestItemQuantityFallback:
    def test_missing_quantity_counts_as_one(self):
        """Иначе SUM(quantity) даст NULL, и подтверждённый чек не даст ни одной попытки —
        тот же дефект, что был на ручном вводе позиций."""
        rows = media_heandler._build_receipt_item_rows([{"name": "Товар"}], {0: 7})
        assert rows[0]["quantity"] == 1.0

    def test_unparsable_quantity_counts_as_one(self):
        rows = media_heandler._build_receipt_item_rows(
            [{"name": "Товар", "quantity": "не число"}], {0: 7}
        )
        assert rows[0]["quantity"] == 1.0

    def test_real_quantity_is_kept(self):
        rows = media_heandler._build_receipt_item_rows(
            [{"name": "Товар", "quantity": 0.476}], {0: 7}
        )
        assert rows[0]["quantity"] == pytest.approx(0.476)


# ---------------------------------------------------------------------------
# process_receipt(): пользователь получает ответ на любой исход
# ---------------------------------------------------------------------------

class TestProcessReceiptAlwaysAnswers:
    def _setup(self, mem_db, monkeypatch, min_quantity=1, progress_message_text=None):
        fake_go = _FakeGlobalObjects()
        monkeypatch.setattr(media_heandler, "global_objects", fake_go)
        monkeypatch.setattr(sql_mgt, "global_objects", fake_go, raising=False)
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(
            mem_db, draw_id, stage_type="standard",
            progress_message_text=progress_message_text,
        )
        rule_id = _insert_rule(
            mem_db, stage_id, title="HARD TEA", aliases="hard tea", min_quantity=min_quantity
        )
        return draw_id, stage_id, rule_id, fake_go

    def test_manual_review_sends_nothing(self, mem_db, monkeypatch):
        """QR нет, ФНС недоступна, OCR не подтвердил — чек уходит к администратору, и
        пользователю НЕ пишут ничего (решение владителя, CLAUDE.md п. 14). Ответ он получит,
        когда администратор примет решение; сам чек при этом обязан попасть в ленту
        уведомлений админки — это проверяется в test_site_bot_progress.py."""
        draw_id, stage_id, _rule, fake_go = self._setup(mem_db, monkeypatch)
        monkeypatch.setattr(media_heandler, "_detect_qr", lambda path: None)
        monkeypatch.setattr(
            media_heandler, "_check_keywords_with_ocr", lambda path, kw: (False, None)
        )
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/manual.jpg", user_tg_id=555, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/manual.jpg"), 555, 100, receipt_id))

        assert run(sql_mgt.get_receipt(receipt_id))["status"] == "На ручной проверке"
        fake_go.bot.send_message.assert_not_awaited()

    def test_error_status_sends_nothing(self, mem_db, monkeypatch):
        """Этап без правил + нечитаемое изображение → «Ошибка»: чек так же ждёт человека."""
        fake_go = _FakeGlobalObjects()
        monkeypatch.setattr(media_heandler, "global_objects", fake_go)
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")  # без правил
        monkeypatch.setattr(media_heandler, "_detect_qr", lambda path: None)
        monkeypatch.setattr(
            media_heandler, "_check_keywords_with_ocr",
            lambda path, kw: (False, "изображение не прочитано"),
        )
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/err.jpg", user_tg_id=556, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/err.jpg"), 556, 101, receipt_id))

        assert run(sql_mgt.get_receipt(receipt_id))["status"] == "Ошибка"
        fake_go.bot.send_message.assert_not_awaited()

    def test_single_unit_rule_sends_configured_text(self, mem_db, monkeypatch):
        """При min_quantity == 1 исход всегда «условия выполнены», и настроенный в панели
        текст раньше не отправлялся никогда — уходило жёстко зашитое «✅ Чек подтверждён»."""
        draw_id, stage_id, _rule, fake_go = self._setup(
            mem_db, monkeypatch,
            progress_message_text="Чек принят ✅\n\nСейчас у вас {entries_count} 🎟️",
        )
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "HARD TEA чёрный чай", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/ok.jpg", user_tg_id=557, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/ok.jpg"), 557, 102, receipt_id))

        assert run(sql_mgt.get_receipt(receipt_id))["status"] == "Подтверждён"
        assert _sent_text(fake_go) == "Чек принят ✅\n\nСейчас у вас 1 попытка выиграть 🎟️"

    def test_never_sends_accepted_with_zero_attempts(self, mem_db, monkeypatch):
        """Если прогресс почему-то нулевой, взаимоисключающий текст не уходит — вместо него
        нейтральное подтверждение."""
        draw_id, stage_id, _rule, fake_go = self._setup(
            mem_db, monkeypatch,
            progress_message_text="Чек принят ✅\n\nСейчас у вас {entries_count} 🎟️",
        )
        _mock_qr_and_fns(monkeypatch, _fns_qr(2), [{"name": "HARD TEA чёрный чай", "quantity": 1}])
        # воспроизводим прод-ситуацию: позиции сохранены без вклада в прогресс
        monkeypatch.setattr(
            sql_mgt, "get_user_rule_progress",
            AsyncMock(return_value={_rule: 0.0}),
        )
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/zero.jpg", user_tg_id=558, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/zero.jpg"), 558, 103, receipt_id))

        text = _sent_text(fake_go)
        assert "0 попыток" not in text
        assert text == receipt_validation.MESSAGE_RECEIPT_CONFIRMED


# ---------------------------------------------------------------------------
# Смена этапов по датам
# ---------------------------------------------------------------------------

class TestActivateDueStages:
    def test_finishes_expired_and_activates_next(self, mem_db):
        """Сценарий прода на 06.10: первый этап истёк, второй лежит в upcoming."""
        today = datetime.date(2026, 10, 6)
        draw_id = _insert_draw(mem_db)
        first = _insert_stage(
            mem_db, draw_id, name="1 месяц", status="active",
            start_date="2026-09-10", end_date="2026-10-05",
        )
        second = _insert_stage(
            mem_db, draw_id, name="2 месяц", status="upcoming",
            start_date="2026-10-06", end_date="2026-11-08",
        )
        result = run(sql_mgt.activate_due_stages(date=today))

        assert result["finished"] == [first]
        assert result["activated"] == second
        assert run(sql_mgt.get_active_stage(date=today))["id"] == second

    def test_keeps_single_active_invariant(self, mem_db):
        """Пока текущий этап не истёк, следующий не включается — активен ровно один."""
        today = datetime.date(2026, 9, 15)
        draw_id = _insert_draw(mem_db)
        first = _insert_stage(
            mem_db, draw_id, status="active", start_date="2026-09-10", end_date="2026-10-05",
        )
        _insert_stage(
            mem_db, draw_id, status="upcoming", start_date="2026-09-01", end_date="2026-12-01",
        )
        result = run(sql_mgt.activate_due_stages(date=today))

        assert result == {"finished": [], "activated": None}
        assert run(sql_mgt.get_active_stage(date=today))["id"] == first

    def test_does_not_activate_stage_that_has_not_started(self, mem_db):
        today = datetime.date(2026, 10, 6)
        draw_id = _insert_draw(mem_db)
        _insert_stage(
            mem_db, draw_id, status="active", start_date="2026-09-10", end_date="2026-10-05",
        )
        _insert_stage(
            mem_db, draw_id, status="upcoming", start_date="2026-11-01", end_date="2026-12-01",
        )
        result = run(sql_mgt.activate_due_stages(date=today))

        assert result["activated"] is None
        assert run(sql_mgt.get_active_stage(date=today)) is None

    def test_is_idempotent(self, mem_db):
        today = datetime.date(2026, 10, 6)
        draw_id = _insert_draw(mem_db)
        _insert_stage(
            mem_db, draw_id, status="active", start_date="2026-09-10", end_date="2026-10-05",
        )
        second = _insert_stage(
            mem_db, draw_id, status="upcoming", start_date="2026-10-06", end_date="2026-11-08",
        )
        run(sql_mgt.activate_due_stages(date=today))
        again = run(sql_mgt.activate_due_stages(date=today))

        assert again == {"finished": [], "activated": None}
        assert run(sql_mgt.get_active_stage(date=today))["id"] == second


# ---------------------------------------------------------------------------
# Сохранение id отправленных сообщений
# ---------------------------------------------------------------------------

class TestSentMessageIds:
    def test_stores_telegram_message_id_and_receipt_link(self, mem_db):
        run(sql_mgt.add_participant_message(
            user_tg_id=42, sender="admin", text="✅ Чек подтверждён",
            tg_message_id=931000, receipt_id=2710,
        ))
        messages = run(sql_mgt.get_receipt_bot_messages(2710))

        assert len(messages) == 1
        assert messages[0]["tg_message_id"] == 931000
        assert messages[0]["user_tg_id"] == 42

    def test_ignores_messages_without_telegram_id(self, mem_db):
        """Старые записи (до доработки) удалить нельзя — их незачем отдавать."""
        run(sql_mgt.add_participant_message(
            user_tg_id=42, sender="admin", text="старое", receipt_id=2710,
        ))
        assert run(sql_mgt.get_receipt_bot_messages(2710)) == []

    def test_excludes_deleted_by_default(self, mem_db):
        row_id = run(sql_mgt.add_participant_message(
            user_tg_id=42, sender="admin", text="текст",
            tg_message_id=931001, receipt_id=2711,
        ))
        run(sql_mgt.mark_message_deleted(row_id))

        assert run(sql_mgt.get_receipt_bot_messages(2711)) == []
        assert len(run(sql_mgt.get_receipt_bot_messages(2711, include_deleted=True))) == 1

    def test_other_receipts_are_not_returned(self, mem_db):
        run(sql_mgt.add_participant_message(
            user_tg_id=42, sender="admin", text="a", tg_message_id=1, receipt_id=1,
        ))
        run(sql_mgt.add_participant_message(
            user_tg_id=42, sender="admin", text="b", tg_message_id=2, receipt_id=2,
        ))
        found = run(sql_mgt.get_receipt_bot_messages(2))

        assert [m["tg_message_id"] for m in found] == [2]

    def test_partial_index_exists(self, mem_db):
        """Индекс по receipt_id должен быть частичным: иначе он растёт вместе со всей
        перепиской (на проде это самая большая таблица в базе)."""
        run(sql_mgt.create_db())
        conn = sqlite3.connect(mem_db)
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='idx_participant_messages_receipt'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "индекс не создан"
        assert "WHERE receipt_id IS NOT NULL" in row[0]
