"""Tests for the guaranteed_prize pipeline helpers in heandlers/media_heandler.py.

Модель "1 активный этап во всей системе" (см. TZ_GUARANTEED_PRIZE_STAGE_TYPES.md и историю
чата с владельцем): process_receipt() всегда оценивает чек по ОДНОМУ этапу — тому, что был
привязан к чеку в момент отправки (receipts.stage_id), не по "текущему активному". Поэтому
интеграционные тесты ниже не обязаны делать stage активным — стадия передаётся напрямую через
add_receipt(stage_id=...), как это делает set_photo().

Requires pyzbar (native zbar) — same DYLD_LIBRARY_PATH requirement as
test_receipt_queue_worker.py, see CLAUDE.md.
"""

import asyncio
import json
import os
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def _insert_stage(db_path, draw_id, name="Этап", stage_type="standard", status="upcoming"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_stages (draw_id, name, stage_type, status) VALUES (?, ?, ?, ?)",
            (draw_id, name, stage_type, status),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_rule(db_path, stage_id, title="Rule", aliases="finsky", min_quantity=1, is_active=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_rules (stage_id, title, aliases, min_quantity, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (stage_id, title, aliases, min_quantity, is_active),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _build_receipt_item_rows (pure) — модель "1 этап" → максимум одно правило на позицию
# ---------------------------------------------------------------------------

class TestBuildReceiptItemRows:
    def test_one_row_per_item_when_no_match(self):
        items = [{"name": "Хлеб", "quantity": 1}]
        rows = media_heandler._build_receipt_item_rows(items, {})
        assert len(rows) == 1
        assert rows[0]["matched_rule_id"] is None

    def test_one_row_per_item_single_match(self):
        items = [{"name": "Водка Finsky", "quantity": 2}]
        rows = media_heandler._build_receipt_item_rows(items, {0: 5})
        assert len(rows) == 1
        assert rows[0]["matched_rule_id"] == 5
        assert rows[0]["quantity"] == 2

    def test_multiple_items_mixed_matches(self):
        items = [
            {"name": "Водка Finsky", "quantity": 1},
            {"name": "Хлеб", "quantity": 1},
        ]
        rows = media_heandler._build_receipt_item_rows(items, {0: 5})
        assert rows[0]["matched_rule_id"] == 5
        assert rows[1]["matched_rule_id"] is None


# ---------------------------------------------------------------------------
# _guaranteed_ocr_rule_id (pure) — атрибуция OCR-прогноза для ОДНОГО этапа
# ---------------------------------------------------------------------------

class TestGuaranteedOcrRuleId:
    def _rule(self, rule_id, aliases="finsky", min_quantity=1, is_active=True):
        return {"id": rule_id, "aliases": aliases, "min_quantity": min_quantity, "is_active": is_active}

    def test_single_min_quantity_one_rule_is_attributable(self):
        rules = [self._rule(1, aliases="finsky", min_quantity=1)]
        keywords, rule_id = media_heandler._guaranteed_ocr_rule_id(rules)
        assert rule_id == 1
        assert keywords == ["finsky"]

    def test_multiple_min_quantity_one_rules_are_ambiguous(self):
        rules = [
            self._rule(1, aliases="finsky", min_quantity=1),
            self._rule(2, aliases="absolut", min_quantity=1),
        ]
        keywords, rule_id = media_heandler._guaranteed_ocr_rule_id(rules)
        assert rule_id is None
        assert keywords == []

    def test_min_quantity_above_one_excluded_from_attribution(self):
        """min_quantity>1 никогда не подтверждается через OCR (раздел 3.4) — не учитывается
        как кандидат на атрибуцию, даже если это единственное правило этапа."""
        rules = [self._rule(1, aliases="finsky", min_quantity=3)]
        keywords, rule_id = media_heandler._guaranteed_ocr_rule_id(rules)
        assert rule_id is None
        assert keywords == []

    def test_inactive_rule_excluded(self):
        rules = [self._rule(1, aliases="finsky", min_quantity=1, is_active=False)]
        keywords, rule_id = media_heandler._guaranteed_ocr_rule_id(rules)
        assert rule_id is None

    def test_no_rules_returns_empty(self):
        keywords, rule_id = media_heandler._guaranteed_ocr_rule_id([])
        assert keywords == []
        assert rule_id is None


# ---------------------------------------------------------------------------
# _looks_like_fns_qr (pure) — t= встречается в проде и как HHMM, и как HHMMSS
# (найдено бенчмарком на реальном чеке "Монетка"/Элемент-Трейд); fns_api._parse_qr_datetime
# уже поддерживает оба формата, эта эвристика должна их не отсеивать раньше времени.
# ---------------------------------------------------------------------------

class TestLooksLikeFnsQr:
    def _qr(self, t):
        return f"t={t}&s=166.00&fn=7380440903074567&i=27711&fp=4204651838&n=1"

    def test_accepts_hhmm_timestamp(self):
        assert media_heandler._looks_like_fns_qr(self._qr("20250326T0843")) is True

    def test_accepts_hhmmss_timestamp(self):
        assert media_heandler._looks_like_fns_qr(self._qr("20260610T165938")) is True

    def test_rejects_malformed_5_digit_time(self):
        assert media_heandler._looks_like_fns_qr(self._qr("20260610T16593")) is False

    def test_rejects_missing_required_field(self):
        payload = "t=20250326T0843&s=219.99&fn=7380440700424677&i=12568&n=1"  # без fp
        assert media_heandler._looks_like_fns_qr(payload) is False

    def test_rejects_non_fiscal_marketing_url(self):
        assert media_heandler._looks_like_fns_qr("https://clck.ru/3GDiUQ") is False

    def test_rejects_empty(self):
        assert media_heandler._looks_like_fns_qr("") is False


# ---------------------------------------------------------------------------
# _is_extra_receipt (DB-only) — теперь принимает стадию напрямую (модель "1 активный этап")
# ---------------------------------------------------------------------------

def test_is_extra_receipt_false_when_stage_none(mem_db):
    assert run(media_heandler._is_extra_receipt(None, 1)) is False


def test_is_extra_receipt_false_for_standard_stage(mem_db):
    """Для standard-этапа «лишнего чека» не бывает — там побед может быть много (лотерея)."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    stage = run(sql_mgt.get_stage(stage_id))
    run(sql_mgt.add_stage_winner(stage_id, 1, None, "Иван"))
    assert run(media_heandler._is_extra_receipt(stage, 1)) is False


def test_is_extra_receipt_false_when_not_yet_winner(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    stage = run(sql_mgt.get_stage(stage_id))
    assert run(media_heandler._is_extra_receipt(stage, 1)) is False


def test_is_extra_receipt_true_when_already_winner(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    stage = run(sql_mgt.get_stage(stage_id))
    run(sql_mgt.add_stage_winner(stage_id, 1, None, "Иван"))
    assert run(media_heandler._is_extra_receipt(stage, 1)) is True


def test_is_extra_receipt_scoped_per_user(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    stage = run(sql_mgt.get_stage(stage_id))
    run(sql_mgt.add_stage_winner(stage_id, 1, None, "Иван"))
    assert run(media_heandler._is_extra_receipt(stage, 2)) is False


# ---------------------------------------------------------------------------
# _resolve_winner_name (DB-only)
# ---------------------------------------------------------------------------

def test_resolve_winner_name_uses_users_table(mem_db):
    conn = sqlite3.connect(mem_db)
    conn.execute("INSERT INTO users (tg_id, name) VALUES (?, ?)", (42, "Пётр"))
    conn.commit()
    conn.close()
    assert run(media_heandler._resolve_winner_name(42)) == "Пётр"


def test_resolve_winner_name_falls_back_to_id_when_unknown(mem_db):
    assert run(media_heandler._resolve_winner_name(999)) == "999"


# ---------------------------------------------------------------------------
# process_receipt() end-to-end (QR+FNS mocked, real DB) — раздел 6/8 ТЗ,
# самый рискованный файл доработки, максимальное покрытие обязательно.
# Чек привязан к стадии через add_receipt(stage_id=...), как это делает set_photo().
# ---------------------------------------------------------------------------

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


class TestProcessReceiptGuaranteedPrizeIntegration:
    def _setup(self, mem_db, monkeypatch, min_quantity=3, title="Водка Finsky", aliases="finsky"):
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
        rule_id = _insert_rule(mem_db, stage_id, title=title, aliases=aliases, min_quantity=min_quantity)
        return draw_id, stage_id, rule_id

    def test_three_receipts_one_each_completes_only_on_third(self, mem_db, monkeypatch):
        """Раздел 8 ТЗ: min_quantity=3, три чека по 1 шт. — выполнено после третьего, не раньше."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=3)
        user_id = 555
        for i in range(1, 4):
            _mock_qr_and_fns(monkeypatch, _fns_qr(i), [{"name": "Водка Finsky", "quantity": 1}])
            receipt_id = run(sql_mgt.add_receipt(
                file_path=f"/tmp/r{i}.jpg", user_tg_id=user_id,
                status="В авто обработке", draw_id=draw_id, stage_id=stage_id,
            ))
            run(media_heandler.process_receipt(Path(f"/tmp/r{i}.jpg"), user_id, 1000 + i, receipt_id))
            is_winner = run(sql_mgt.is_stage_winner(stage_id, user_id))
            if i < 3:
                assert is_winner is False, f"should not win yet after receipt {i}"
            else:
                assert is_winner is True, "should win after the 3rd receipt"
        winner_row = run(sql_mgt.get_receipt(receipt_id))
        assert winner_row["status"] == "Подтверждён"

    def test_single_receipt_meets_threshold_at_once(self, mem_db, monkeypatch):
        """Раздел 8 ТЗ: min_quantity=3 закрыт ОДНИМ чеком с quantity=3 в одной строке."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=3)
        user_id = 777
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Водка Finsky", "quantity": 3}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/single.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/single.jpg"), user_id, 2000, receipt_id))
        assert run(sql_mgt.is_stage_winner(stage_id, user_id)) is True

    def test_progress_receipt_sends_progress_message_not_generic_confirm(self, mem_db, monkeypatch):
        """Раздел 3.5 ТЗ: промежуточный принятый чек шлёт «Осталось...», НЕ «✅ Чек подтверждён»."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=2)
        user_id = 111
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Водка Finsky", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/prog.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/prog.jpg"), user_id, 4000, receipt_id))
        fake_go = media_heandler.global_objects
        fake_go.bot.send_message.assert_awaited_once()
        sent_text = fake_go.bot.send_message.call_args.args[1]
        assert sent_text != "✅ Чек подтверждён"
        assert "1" in sent_text  # остаток 1 шт.

    def test_win_receipt_sends_win_message(self, mem_db, monkeypatch):
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=1)
        user_id = 222
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Водка Finsky", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/win.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/win.jpg"), user_id, 5000, receipt_id))
        fake_go = media_heandler.global_objects
        sent_text = fake_go.bot.send_message.call_args.args[1]
        assert "Поздравляем" in sent_text

    def test_extra_receipt_after_win_marked_and_short_circuited(self, mem_db, monkeypatch):
        """Раздел 4.4/9 ТЗ: после победы следующий чек — «Лишний чек», без повторного QR/ФНС."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=1)
        user_id = 333
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Водка Finsky", "quantity": 1}])
        r1 = run(sql_mgt.add_receipt(
            file_path="/tmp/e1.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/e1.jpg"), user_id, 6000, r1))
        assert run(sql_mgt.is_stage_winner(stage_id, user_id)) is True

        # второй чек: process_receipt должен вернуться сразу на "Лишний чек" без вызова
        # мока _detect_qr/get_receipt_by_qr для нового чека (мы намеренно НЕ обновляем мок —
        # если бы дошло до QR-логики, использовался бы старый qr=_fns_qr(1) => "уже загружен",
        # а не "Лишний чек"; получение именно "Лишний чек" доказывает, что сработал ранний выход)
        r2 = run(sql_mgt.add_receipt(
            file_path="/tmp/e2.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/e2.jpg"), user_id, 6001, r2))
        receipt2 = run(sql_mgt.get_receipt(r2))
        assert receipt2["status"] == "Лишний чек"

    def test_standard_stage_confirms_via_own_rules(self, mem_db, monkeypatch):
        """Модель "1 активный этап": чек оценивается ровно по стадии, к которой привязан —
        standard-этап со своими правилами работает так же, как раньше (регрессия)."""
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        s_stage = _insert_stage(mem_db, draw_id, name="Standard", stage_type="standard")
        _insert_rule(mem_db, s_stage, title="Ром", aliases="bacardi", min_quantity=1)

        user_id = 444
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Ром Bacardi", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/indep.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=s_stage,
        ))
        run(media_heandler.process_receipt(Path("/tmp/indep.jpg"), user_id, 7000, receipt_id))

        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "Подтверждён"


# ---------------------------------------------------------------------------
# process_receipt() standard-этап с накопительным прогрессом — та же модель, что и
# guaranteed_prize, но НИКОГДА не выигрывает автоматически: полное выполнение условий
# только допускает к розыгрышу (build_standard_qualify_message), победителя по-прежнему
# выбирает админ вручную через determine().
# ---------------------------------------------------------------------------

class TestProcessReceiptStandardStageIntegration:
    def _setup(self, mem_db, monkeypatch, min_quantity=3, title="Настойка", aliases="настойка"):
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
        rule_id = _insert_rule(mem_db, stage_id, title=title, aliases=aliases, min_quantity=min_quantity)
        return draw_id, stage_id, rule_id

    def test_partial_match_confirms_receipt_and_sends_progress_message(self, mem_db, monkeypatch):
        """Раздел "2 из 3" — частичное совпадение автоматически подтверждает чек и шлёт
        сообщение об остатке, НЕ "✅ Чек подтверждён" и НЕ уходит на ручную проверку."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=3)
        user_id = 2001
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Настойка Ром", "quantity": 2}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/std_partial.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/std_partial.jpg"), user_id, 9000, receipt_id))
        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "Подтверждён"
        fake_go = media_heandler.global_objects
        sent_text = fake_go.bot.send_message.call_args.args[1]
        assert sent_text != "✅ Чек подтверждён"
        assert "1" in sent_text  # остаток 1 шт.
        assert "бот" not in sent_text.lower()  # раздел "убрать про бота"
        # 2 из 3 — комплект ещё не собран (попытка = комплект, не число чеков)
        assert "0 попыток выиграть" in sent_text

    def test_accumulates_across_multiple_receipts_then_qualifies(self, mem_db, monkeypatch):
        """Накопление 2 + 1 = 3 через два разных чека закрывает условие на втором чеке."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=3)
        user_id = 2002
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Настойка Ром", "quantity": 2}])
        r1 = run(sql_mgt.add_receipt(
            file_path="/tmp/std_acc1.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/std_acc1.jpg"), user_id, 9001, r1))

        _mock_qr_and_fns(monkeypatch, _fns_qr(2), [{"name": "Настойка Ром", "quantity": 1}])
        r2 = run(sql_mgt.add_receipt(
            file_path="/tmp/std_acc2.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/std_acc2.jpg"), user_id, 9002, r2))

        fake_go = media_heandler.global_objects
        sent_text = fake_go.bot.send_message.call_args.args[1]
        # 2 шт. + 1 шт. = 3 шт. накоплено при min_quantity=3 — это РОВНО 1 комплект/попытка,
        # не 2 (попытка — не число чеков, а число собранных комплектов условия)
        assert sent_text == media_heandler.receipt_validation.build_standard_qualify_message(None, 1)
        assert "1 попытка выиграть" in sent_text
        assert "Поздравляем" not in sent_text  # это НЕ текст победы guaranteed_prize

    def test_owner_example_2_receipts_1_entry_then_3rd_receipt_gives_2(self, mem_db, monkeypatch):
        """End-to-end через process_receipt() дословного примера владельца: "загрузили 2
        чека и только так прошло на 1 попытку. Потом третий грузанули и там сразу все
        условия. Чека 3, а попытки 2"."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=2)
        user_id = 2004
        fake_go = media_heandler.global_objects

        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Настойка Ром", "quantity": 1}])
        r1 = run(sql_mgt.add_receipt(
            file_path="/tmp/owner1.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/owner1.jpg"), user_id, 9010, r1))
        assert "0 попыток выиграть" in fake_go.bot.send_message.call_args.args[1]

        _mock_qr_and_fns(monkeypatch, _fns_qr(2), [{"name": "Настойка Ром", "quantity": 1}])
        r2 = run(sql_mgt.add_receipt(
            file_path="/tmp/owner2.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/owner2.jpg"), user_id, 9011, r2))
        sent_text = fake_go.bot.send_message.call_args.args[1]
        assert sent_text == media_heandler.receipt_validation.build_standard_qualify_message(None, 1)

        _mock_qr_and_fns(monkeypatch, _fns_qr(3), [{"name": "Настойка Ром", "quantity": 2}])
        r3 = run(sql_mgt.add_receipt(
            file_path="/tmp/owner3.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/owner3.jpg"), user_id, 9012, r3))
        sent_text = fake_go.bot.send_message.call_args.args[1]
        assert sent_text == media_heandler.receipt_validation.build_standard_qualify_message(None, 2)

    def test_full_match_never_writes_winner(self, mem_db, monkeypatch):
        """Критичный regression-guard: standard-этап никогда не выигрывает автоматически,
        даже когда условия полностью выполнены одним чеком."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=1)
        user_id = 2003
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Настойка Ром", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/std_full.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/std_full.jpg"), user_id, 9003, receipt_id))
        assert run(sql_mgt.is_stage_winner(stage_id, user_id)) is False
        winners = run(sql_mgt.get_stage_progress(stage_id))
        assert winners[0]["complete"] is True


# ---------------------------------------------------------------------------
# process_receipt() авто-отказ при QR+ФНС без совпадения (раздел про "Нет товара в чеке" —
# ФНС считается надёжным источником, ручная подстраховка сознательно убрана). Самый ценный
# новый тест: именно этот сценарий сегодня живьём поймал баг с алиасом "настойка" vs
# реальным сокращением ФНС "Наст." — если бы авто-отказ уже стоял, бот бы соврал "нет
# товара" при реально присутствующем товаре. Здесь alias подобран так, чтобы РЕАЛЬНО не
# совпадать с товаром (в отличие от того бага) — проверяем корректный отказ, не баг.
# ---------------------------------------------------------------------------

class TestProcessReceiptAutoRejectNoMatch:
    def test_guaranteed_prize_no_match_auto_rejects(self, mem_db, monkeypatch):
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
        _insert_rule(mem_db, stage_id, title="Водка Finsky", aliases="finsky", min_quantity=1)
        user_id = 3001
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Хлеб бородинский", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/reject1.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/reject1.jpg"), user_id, 9100, receipt_id))
        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "Нет товара в чеке"

    def test_standard_no_match_auto_rejects(self, mem_db, monkeypatch):
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
        _insert_rule(mem_db, stage_id, title="Водка Finsky", aliases="finsky", min_quantity=1)
        user_id = 3002
        _mock_qr_and_fns(monkeypatch, _fns_qr(1), [{"name": "Хлеб бородинский", "quantity": 1}])
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/reject2.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/reject2.jpg"), user_id, 9101, receipt_id))
        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "Нет товара в чеке"


# ---------------------------------------------------------------------------
# process_receipt() OCR-fallback path (QR не найден) — раздел 3.4 ТЗ: единое правило
# min_quantity==1 → OCR может подтвердить; min_quantity>1 → никогда.
# ---------------------------------------------------------------------------

def _mock_no_qr_and_ocr(monkeypatch, keyword_hit: bool):
    """Реалистичный мок _check_keywords_with_ocr: как настоящая функция, при пустом списке
    ключевых слов всегда возвращает False (совпадений искать не в чем)."""
    monkeypatch.setattr(media_heandler, "_detect_qr", lambda path: None)

    def fake_ocr(path, keywords):
        if not keywords:
            return False, "ключевые слова не настроены"
        return keyword_hit, None

    monkeypatch.setattr(media_heandler, "_check_keywords_with_ocr", fake_ocr)


class TestProcessReceiptOcrFallbackGuaranteedPrize:
    def _setup(self, mem_db, monkeypatch, min_quantity):
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
        rule_id = _insert_rule(mem_db, stage_id, title="Водка Finsky", aliases="finsky", min_quantity=min_quantity)
        return draw_id, stage_id, rule_id

    def test_min_quantity_one_ocr_confirms_and_tracks_progress(self, mem_db, monkeypatch):
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=1)
        _mock_no_qr_and_ocr(monkeypatch, keyword_hit=True)
        user_id = 999
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/ocr1.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/ocr1.jpg"), user_id, 8000, receipt_id))
        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "Подтверждён"
        assert run(sql_mgt.is_stage_winner(stage_id, user_id)) is True

    def test_min_quantity_above_one_never_ocr_confirmed(self, mem_db, monkeypatch):
        """min_quantity=3 без QR — правило исключено из OCR-ключевых слов (раздел 3.4), чек
        уходит на ручную проверку, даже если бы OCR теоретически «нашёл» текст."""
        draw_id, stage_id, rule_id = self._setup(mem_db, monkeypatch, min_quantity=3)
        _mock_no_qr_and_ocr(monkeypatch, keyword_hit=True)  # даже если бы OCR сработал...
        user_id = 1000
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/ocr2.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/ocr2.jpg"), user_id, 8001, receipt_id))
        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "На ручной проверке"
        assert run(sql_mgt.is_stage_winner(stage_id, user_id)) is False

    def test_standard_stage_min_quantity_above_one_still_manual_review_without_qr(self, mem_db, monkeypatch):
        """Регрессия раздела 3.4 для standard-этапа (уже действующее поведение, не должно
        было измениться этой доработкой)."""
        monkeypatch.setattr(media_heandler, "global_objects", _FakeGlobalObjects())
        draw_id = _insert_draw(mem_db)
        stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
        _insert_rule(mem_db, stage_id, title="Водка Finsky", aliases="finsky", min_quantity=3)
        _mock_no_qr_and_ocr(monkeypatch, keyword_hit=True)
        user_id = 1001
        receipt_id = run(sql_mgt.add_receipt(
            file_path="/tmp/ocr3.jpg", user_tg_id=user_id, status="В авто обработке",
            draw_id=draw_id, stage_id=stage_id,
        ))
        run(media_heandler.process_receipt(Path("/tmp/ocr3.jpg"), user_id, 8002, receipt_id))
        receipt_row = run(sql_mgt.get_receipt(receipt_id))
        assert receipt_row["status"] == "На ручной проверке"
