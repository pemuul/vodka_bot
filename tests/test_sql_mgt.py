"""Tests for sql_mgt.py — schema parsing, helpers, DB operations."""

import asyncio
import json
import os
import sqlite3
import tempfile
import pytest
from pathlib import Path
import sys
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite
import sql_mgt


# ---------------------------------------------------------------------------
# Helper: run a coroutine synchronously in tests
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixture: in-memory-backed SQLite database with full project schema
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_db(monkeypatch):
    """Patch sql_mgt.db_name to a temp file with full schema applied."""
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


# ---------------------------------------------------------------------------
# Schema parsing helpers (pure functions, no I/O)
# ---------------------------------------------------------------------------

class TestParseSchemaParts:
    def test_simple_columns(self):
        body = "id INTEGER, name TEXT NOT NULL"
        parts = sql_mgt._split_schema_parts(body)
        assert parts == ["id INTEGER", "name TEXT NOT NULL"]

    def test_nested_parentheses_not_split(self):
        body = "id INTEGER, UNIQUE(user_tg_id, visit_date)"
        parts = sql_mgt._split_schema_parts(body)
        assert len(parts) == 2
        assert "UNIQUE(user_tg_id, visit_date)" in parts

    def test_empty_body_returns_empty(self):
        assert sql_mgt._split_schema_parts("") == []

    def test_single_column(self):
        parts = sql_mgt._split_schema_parts("id INTEGER PRIMARY KEY AUTOINCREMENT")
        assert parts == ["id INTEGER PRIMARY KEY AUTOINCREMENT"]


class TestParseTableSchema:
    def test_basic_create_statement(self):
        ddl = "users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        columns = sql_mgt._parse_table_schema(ddl)
        names = [c[0] for c in columns]
        assert "id" in names
        assert "name" in names

    def test_skips_constraints(self):
        ddl = "t (id INTEGER, UNIQUE(a,b), PRIMARY KEY (id))"
        columns = sql_mgt._parse_table_schema(ddl)
        names = [c[0] for c in columns]
        assert "id" in names
        assert "UNIQUE" not in names
        assert "PRIMARY" not in names

    def test_column_types_extracted(self):
        ddl = "t (amount REAL, flag BOOLEAN DEFAULT FALSE)"
        columns = sql_mgt._parse_table_schema(ddl)
        col_dict = dict(columns)
        assert "REAL" in col_dict["amount"]
        assert "BOOLEAN" in col_dict["flag"]


class TestGetTableSchemaColumns:
    def test_returns_columns_for_known_table(self):
        columns = sql_mgt.get_table_schema_columns("users")
        names = [c[0] for c in columns]
        assert "tg_id" in names
        assert "name" in names

    def test_returns_empty_for_unknown_table(self):
        assert sql_mgt.get_table_schema_columns("nonexistent_table_xyz") == []

    def test_receipts_schema_has_required_fields(self):
        columns = sql_mgt.get_table_schema_columns("receipts")
        names = [c[0] for c in columns]
        for expected in ("id", "number", "date", "amount", "user_tg_id", "status", "qr"):
            assert expected in names, f"Expected column '{expected}' in receipts"


# ---------------------------------------------------------------------------
# RECEIPT_COLUMNS_ORDER and normalisation helpers
# ---------------------------------------------------------------------------

class TestReceiptColumnHelpers:
    def test_column_names_match_order(self):
        names = list(sql_mgt.RECEIPT_COLUMN_NAMES)
        order_names = [col for col, _ in sql_mgt.RECEIPT_COLUMNS_ORDER]
        assert names == order_names

    def test_normalise_valid_id(self):
        used: set = set()
        assert sql_mgt._normalise_receipt_id_value(5, used) == 5
        assert 5 in used

    def test_normalise_duplicate_id_returns_none(self):
        used = {5}
        assert sql_mgt._normalise_receipt_id_value(5, used) is None

    def test_normalise_zero_returns_none(self):
        assert sql_mgt._normalise_receipt_id_value(0, set()) is None

    def test_normalise_negative_returns_none(self):
        assert sql_mgt._normalise_receipt_id_value(-1, set()) is None

    def test_normalise_string_integer(self):
        used: set = set()
        assert sql_mgt._normalise_receipt_id_value("10", used) == 10

    def test_normalise_empty_string_returns_none(self):
        assert sql_mgt._normalise_receipt_id_value("", set()) is None

    def test_normalise_non_numeric_string_returns_none(self):
        assert sql_mgt._normalise_receipt_id_value("abc", set()) is None

    def test_prepare_receipt_rows_deduplicates(self):
        rows = [
            (5, "number1", "2025-01-01", 100.0, 1, None, None, None, "path", "ok", None, None),
            (5, "number2", "2025-01-02", 200.0, 2, None, None, None, "path2", "ok", None, None),
        ]
        result = sql_mgt._prepare_receipt_rows(rows)
        assert result[0][0] == 5
        assert result[1][0] is None


# ---------------------------------------------------------------------------
# Database operations via tmp file SQLite
# ---------------------------------------------------------------------------

def test_add_receipt_returns_id(mem_db):
    receipt_id = run(sql_mgt.add_receipt(
        file_path="/tmp/test_receipt.jpg",
        user_tg_id=12345,
        status="не подтвержден",
        number="TEST-001",
        date="2025-04-12",
        amount=199.99,
    ))
    assert isinstance(receipt_id, int)
    assert receipt_id > 0


def test_get_receipt_returns_dict(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/check.jpg",
        user_tg_id=99,
        status="не подтвержден",
    ))
    receipt = run(sql_mgt.get_receipt(rid))
    assert receipt is not None
    assert receipt["id"] == rid
    assert receipt["user_tg_id"] == 99


def test_update_receipt_status(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/check2.jpg",
        user_tg_id=42,
        status="не подтвержден",
    ))
    old = run(sql_mgt.update_receipt_status(rid, "подтвержден", comment="ОК"))
    assert old == "не подтвержден"
    receipt = run(sql_mgt.get_receipt(rid))
    assert receipt["status"] == "подтвержден"
    assert receipt["comment"] == "ОК"


def test_enqueue_and_acquire_receipt(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/queue_check.jpg",
        user_tg_id=7,
        status="не подтвержден",
    ))
    run(sql_mgt.enqueue_receipt_ocr(rid))
    job = run(sql_mgt.acquire_next_receipt_for_ocr(lock_timeout_seconds=300))
    assert job is not None
    queue_id, receipt_id, attempt = job
    assert receipt_id == rid
    assert attempt == 1


def test_mark_receipt_queue_complete(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/done.jpg",
        user_tg_id=8,
        status="не подтвержден",
    ))
    run(sql_mgt.enqueue_receipt_ocr(rid))
    job = run(sql_mgt.acquire_next_receipt_for_ocr())
    queue_id, _, _ = job
    run(sql_mgt.mark_receipt_queue_complete(queue_id))

    next_job = run(sql_mgt.acquire_next_receipt_for_ocr())
    assert next_job is None


def test_find_receipt_by_qr(mem_db):
    qr_string = "t=20250412T1942&s=100.00&fn=1&i=2&fp=3&n=1"
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/qr_check.jpg",
        user_tg_id=55,
        status="не подтвержден",
        qr=qr_string,
    ))
    found_id = run(sql_mgt.find_receipt_by_qr(qr_string))
    assert found_id == rid


def test_find_receipt_by_qr_not_found(mem_db):
    found = run(sql_mgt.find_receipt_by_qr("nonexistent_qr_value"))
    assert found is None


def test_add_participant_message(mem_db):
    msg_id = run(sql_mgt.add_participant_message(
        user_tg_id=100,
        sender="user",
        text="Привет",
    ))
    assert isinstance(msg_id, int)
    assert msg_id > 0


def test_get_active_draw_id_no_draws(mem_db):
    result = run(sql_mgt.get_active_draw_id())
    assert result is None


def test_enqueue_receipt_idempotent(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/idem.jpg",
        user_tg_id=1,
        status="не подтвержден",
    ))
    run(sql_mgt.enqueue_receipt_ocr(rid))
    run(sql_mgt.enqueue_receipt_ocr(rid))  # idempotent
    job = run(sql_mgt.acquire_next_receipt_for_ocr())
    assert job is not None
    assert job[1] == rid


def test_receipt_status_returns_previous(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/prev.jpg",
        user_tg_id=77,
        status="не подтвержден",
    ))
    old = run(sql_mgt.update_receipt_status(rid, "ошибка"))
    assert old == "не подтвержден"
    old2 = run(sql_mgt.update_receipt_status(rid, "подтвержден"))
    assert old2 == "ошибка"


# ---------------------------------------------------------------------------
# get_next_month_date (pure date arithmetic)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Schema: new columns/tables for draw auto-validation and rules (TZ_ACTION_VALIDATION_SETTINGS)
# ---------------------------------------------------------------------------

class TestNewSchemaEntries:
    def test_prize_draws_is_dataless_container(self):
        """Акция — контейнер без своих данных (даты/статус/автовалидация переехали на
        этап, см. чат с владельцем про "1 активный этап во всей системе")."""
        columns = sql_mgt.get_table_schema_columns("prize_draws")
        names = [c[0] for c in columns]
        assert names == ["id", "title", "create_dt"]

    def test_prize_draw_stages_has_dates_status_autovalidation(self):
        columns = sql_mgt.get_table_schema_columns("prize_draw_stages")
        col_dict = dict(columns)
        assert "start_date" in col_dict
        assert "end_date" in col_dict
        assert "status" in col_dict
        assert "DEFAULT 'upcoming'" in col_dict["status"]
        assert "auto_validation_enabled" in col_dict

    def test_receipts_has_stage_id_column(self):
        columns = sql_mgt.get_table_schema_columns("receipts")
        names = [c[0] for c in columns]
        assert "stage_id" in names

    def test_prize_draw_rules_schema(self):
        columns = sql_mgt.get_table_schema_columns("prize_draw_rules")
        names = [c[0] for c in columns]
        for expected in ("id", "stage_id", "title", "sku_code", "aliases", "min_quantity", "is_active"):
            assert expected in names, f"Expected column '{expected}' in prize_draw_rules"
        assert "draw_id" not in names, "prize_draw_rules.draw_id должен был переехать на stage_id"

    def test_prize_draw_stages_has_type_and_message_columns(self):
        columns = sql_mgt.get_table_schema_columns("prize_draw_stages")
        col_dict = dict(columns)
        assert "stage_type" in col_dict
        assert "DEFAULT 'standard'" in col_dict["stage_type"]
        assert "progress_message_text" in col_dict
        assert "win_message_text" in col_dict

    def test_receipt_items_schema(self):
        columns = sql_mgt.get_table_schema_columns("receipt_items")
        names = [c[0] for c in columns]
        for expected in ("id", "receipt_id", "raw_name", "quantity", "price", "sum", "matched_rule_id"):
            assert expected in names, f"Expected column '{expected}' in receipt_items"


# ---------------------------------------------------------------------------
# get_active_stage (заменил get_active_draw_id/get_draw_auto_validation — модель
# "1 активный этап во всей системе")
# ---------------------------------------------------------------------------

def _insert_draw(db_path, title="Test draw"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("INSERT INTO prize_draws (title) VALUES (?)", (title,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_stage(
    db_path, draw_id, name="Этап 1", stage_type="standard", order_index=0,
    status="upcoming", start_date="2020-01-01", end_date="2999-01-01",
    auto_validation_enabled=1,
):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_stages "
            "(draw_id, name, stage_type, order_index, status, start_date, end_date, "
            "auto_validation_enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (draw_id, name, stage_type, order_index, status, start_date, end_date,
             auto_validation_enabled),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_get_active_stage_none_when_no_active(mem_db):
    draw_id = _insert_draw(mem_db)
    _insert_stage(mem_db, draw_id, status="upcoming")
    assert run(sql_mgt.get_active_stage()) is None


def test_get_active_stage_returns_active_stage(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, status="active")
    stage = run(sql_mgt.get_active_stage())
    assert stage is not None
    assert stage["id"] == stage_id
    assert stage["draw_id"] == draw_id


def test_get_active_stage_respects_date_range(mem_db):
    draw_id = _insert_draw(mem_db)
    _insert_stage(
        mem_db, draw_id, status="active",
        start_date="2099-01-01", end_date="2099-12-31",
    )
    assert run(sql_mgt.get_active_stage()) is None


def test_get_active_stage_null_dates_means_no_restriction(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, status="active", start_date=None, end_date=None)
    stage = run(sql_mgt.get_active_stage())
    assert stage is not None
    assert stage["id"] == stage_id


def test_get_active_draw_id_wraps_active_stage(mem_db):
    draw_id = _insert_draw(mem_db)
    _insert_stage(mem_db, draw_id, status="active")
    assert run(sql_mgt.get_active_draw_id()) == draw_id


def test_get_active_draw_id_none_when_no_active_stage(mem_db):
    assert run(sql_mgt.get_active_draw_id()) is None


def _insert_rule(db_path, stage_id, title="Финская водка", aliases="finsky;фински", min_quantity=1, is_active=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_rules (stage_id, title, sku_code, aliases, min_quantity, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (stage_id, title, "finsky-vodka", aliases, min_quantity, is_active),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_get_stage_rules_empty_when_none(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id)
    assert run(sql_mgt.get_stage_rules(stage_id)) == []


def test_get_stage_rules_returns_active_only(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id)
    _insert_rule(mem_db, stage_id, title="Active rule", is_active=1)
    _insert_rule(mem_db, stage_id, title="Inactive rule", is_active=0)
    rules = run(sql_mgt.get_stage_rules(stage_id))
    assert len(rules) == 1
    assert rules[0]["title"] == "Active rule"


def test_get_stage_rules_only_active_false_returns_all(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id)
    _insert_rule(mem_db, stage_id, title="Active rule", is_active=1)
    _insert_rule(mem_db, stage_id, title="Inactive rule", is_active=0)
    rules = run(sql_mgt.get_stage_rules(stage_id, only_active=False))
    assert len(rules) == 2


def test_get_stage_rules_not_visible_in_other_stage(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_a = _insert_stage(mem_db, draw_id, name="A")
    stage_b = _insert_stage(mem_db, draw_id, name="B")
    _insert_rule(mem_db, stage_a, title="Only in A")
    assert len(run(sql_mgt.get_stage_rules(stage_a))) == 1
    assert run(sql_mgt.get_stage_rules(stage_b)) == []


def test_get_draw_stages_returns_stage_type(mem_db):
    draw_id = _insert_draw(mem_db)
    _insert_stage(mem_db, draw_id, name="Standard stage", stage_type="standard", order_index=0)
    _insert_stage(mem_db, draw_id, name="Guaranteed stage", stage_type="guaranteed_prize", order_index=1)
    stages = run(sql_mgt.get_draw_stages(draw_id))
    assert [s["name"] for s in stages] == ["Standard stage", "Guaranteed stage"]
    assert [s["stage_type"] for s in stages] == ["standard", "guaranteed_prize"]


def test_get_draw_stages_empty_for_unknown_draw(mem_db):
    assert run(sql_mgt.get_draw_stages(999999)) == []


def test_new_stage_defaults_to_standard_type(mem_db):
    """Обратная совместимость: этап без явного типа — standard (раздел 8 ТЗ)."""
    draw_id = _insert_draw(mem_db)
    conn = sqlite3.connect(mem_db)
    conn.execute(
        "INSERT INTO prize_draw_stages (draw_id, name) VALUES (?, ?)",
        (draw_id, "Legacy stage"),
    )
    conn.commit()
    conn.close()
    stages = run(sql_mgt.get_draw_stages(draw_id))
    assert stages[0]["stage_type"] == "standard"


# ---------------------------------------------------------------------------
# get_user_rule_progress / is_stage_winner / add_stage_winner (накопительный прогресс)
# ---------------------------------------------------------------------------

def _insert_receipt_item(db_path, receipt_id, matched_rule_id, quantity):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO receipt_items (receipt_id, raw_name, quantity, price, sum, matched_rule_id) "
            "VALUES (?, 'test item', ?, NULL, NULL, ?)",
            (receipt_id, quantity, matched_rule_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_user_rule_progress_sums_confirmed_receipts_only(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=3)

    r1 = run(sql_mgt.add_receipt(file_path="/tmp/r1.jpg", user_tg_id=1, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 1)
    r2 = run(sql_mgt.add_receipt(file_path="/tmp/r2.jpg", user_tg_id=1, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r2, rule_id, 1)
    # чек на ручной проверке НЕ должен учитываться (11.7)
    r3 = run(sql_mgt.add_receipt(file_path="/tmp/r3.jpg", user_tg_id=1, status="На ручной проверке", draw_id=draw_id))
    _insert_receipt_item(mem_db, r3, rule_id, 5)

    progress = run(sql_mgt.get_user_rule_progress(1, draw_id, [rule_id]))
    assert progress[rule_id] == 2.0


def test_user_rule_progress_single_receipt_meets_threshold(mem_db):
    """min_quantity=3, один чек содержит quantity=3 -> выполнено одним чеком (раздел 4.6)."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=3)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/r1.jpg", user_tg_id=2, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 3)
    progress = run(sql_mgt.get_user_rule_progress(2, draw_id, [rule_id]))
    assert progress[rule_id] == 3.0


def test_user_rule_progress_scoped_to_user_and_draw(mem_db):
    draw_id = _insert_draw(mem_db)
    other_draw_id = _insert_draw(mem_db, title="Other draw")
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=1)

    mine = run(sql_mgt.add_receipt(file_path="/tmp/mine.jpg", user_tg_id=10, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, mine, rule_id, 1)
    other_user = run(sql_mgt.add_receipt(file_path="/tmp/other.jpg", user_tg_id=11, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, other_user, rule_id, 1)

    progress = run(sql_mgt.get_user_rule_progress(10, draw_id, [rule_id]))
    assert progress[rule_id] == 1.0


def test_user_rule_progress_missing_rule_defaults_zero(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=2)
    progress = run(sql_mgt.get_user_rule_progress(99, draw_id, [rule_id]))
    assert progress[rule_id] == 0.0


def test_is_stage_winner_false_by_default(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    assert run(sql_mgt.is_stage_winner(stage_id, 123)) is False


def test_add_stage_winner_then_is_stage_winner_true(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    run(sql_mgt.add_stage_winner(stage_id, 123, receipt_id=None, winner_name="Иван"))
    assert run(sql_mgt.is_stage_winner(stage_id, 123)) is True
    assert run(sql_mgt.is_stage_winner(stage_id, 456)) is False


# ---------------------------------------------------------------------------
# evaluate_guaranteed_prize_stage (общая для автопайплайна и ручного подтверждения)
# ---------------------------------------------------------------------------

def test_evaluate_guaranteed_prize_no_rules(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_guaranteed_prize_stage(stage, 1, draw_id, None, "Иван"))
    assert result == {"outcome": "no_rules"}


def test_evaluate_guaranteed_prize_already_winner(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    _insert_rule(mem_db, stage_id, min_quantity=1)
    run(sql_mgt.add_stage_winner(stage_id, 1, None, "Иван"))
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_guaranteed_prize_stage(stage, 1, draw_id, None, "Иван"))
    assert result == {"outcome": "already_winner"}


def test_evaluate_guaranteed_prize_progress_not_yet_complete(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, title="Водка", min_quantity=2)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/p1.jpg", user_tg_id=5, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 1)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_guaranteed_prize_stage(stage, 5, draw_id, r1, "Пётр"))
    assert result["outcome"] == "progress"
    assert result["rule_progress"][0]["progress"] == 1.0
    assert run(sql_mgt.is_stage_winner(stage_id, 5)) is False


def test_evaluate_guaranteed_prize_completes_and_adds_winner(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, title="Водка", min_quantity=2)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/c1.jpg", user_tg_id=6, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 2)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_guaranteed_prize_stage(stage, 6, draw_id, r1, "Мария"))
    assert result["outcome"] == "won"
    assert run(sql_mgt.is_stage_winner(stage_id, 6)) is True


def test_evaluate_guaranteed_prize_multiple_rules_all_required(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_a = _insert_rule(mem_db, stage_id, title="Водка", min_quantity=1)
    rule_b = _insert_rule(mem_db, stage_id, title="Джин", min_quantity=1)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/m1.jpg", user_tg_id=7, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_a, 1)
    stage = {"id": stage_id}
    # только правило A выполнено — этап ещё не завершён (частичное выполнение — не победа)
    result = run(sql_mgt.evaluate_guaranteed_prize_stage(stage, 7, draw_id, r1, "Олег"))
    assert result["outcome"] == "progress"
    assert run(sql_mgt.is_stage_winner(stage_id, 7)) is False


# ---------------------------------------------------------------------------
# evaluate_standard_stage_progress — та же модель накопления, что и guaranteed_prize,
# но НИКОГДА не пишет в prize_draw_winners (победитель standard-этапа выбирается вручную)
# ---------------------------------------------------------------------------

def test_evaluate_standard_progress_no_rules(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 1, draw_id))
    assert result == {"outcome": "no_rules"}


def test_evaluate_standard_progress_not_yet_complete(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=3)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/s1.jpg", user_tg_id=20, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 2)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 20, draw_id))
    assert result["outcome"] == "progress"
    assert result["rule_progress"][0]["progress"] == 2.0


def test_evaluate_standard_progress_completes_without_writing_winner(mem_db):
    """Критичный regression-guard: standard-этап никогда не выигрывает автоматически —
    в отличие от guaranteed_prize, complete НЕ должно добавлять запись в prize_draw_winners."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=3)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/s2.jpg", user_tg_id=21, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 3)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 21, draw_id))
    assert result["outcome"] == "complete"
    assert run(sql_mgt.is_stage_winner(stage_id, 21)) is False


def test_evaluate_standard_progress_multiple_rules_all_required(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_a = _insert_rule(mem_db, stage_id, title="Водка", min_quantity=1)
    rule_b = _insert_rule(mem_db, stage_id, title="Джин", min_quantity=1)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/s3.jpg", user_tg_id=22, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_a, 1)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 22, draw_id))
    assert result["outcome"] == "progress"


def test_evaluate_standard_progress_entries_count_is_sets_not_receipts(mem_db):
    """Уточнение владельца: "не просто каждый чек, а группа чеков от 1 и более в
    совокупности проходящая валидацию". min_quantity=2: два чека по 1 шт. каждый вместе
    дают ровно 1 попытку (не 2) — это ОДИН комплект, собранный из двух чеков."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=2)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/e1.jpg", user_tg_id=23, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 1)
    r2 = run(sql_mgt.add_receipt(file_path="/tmp/e2.jpg", user_tg_id=23, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r2, rule_id, 1)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 23, draw_id))
    assert result["outcome"] == "complete"
    assert result["entries_count"] == 1


def test_evaluate_standard_progress_owner_example_2_receipts_1_entry_then_3rd_gives_2(mem_db):
    """Дословный пример владельца: "загрузили 2 чека и только так прошло на 1 попытку.
    Потом третий грузанули и там сразу все условия. Чека 3, а попытки 2"."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=2)
    stage = {"id": stage_id}

    r1 = run(sql_mgt.add_receipt(file_path="/tmp/o1.jpg", user_tg_id=26, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 1)
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 26, draw_id))
    assert result["entries_count"] == 0  # первого чека одного недостаточно

    r2 = run(sql_mgt.add_receipt(file_path="/tmp/o2.jpg", user_tg_id=26, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r2, rule_id, 1)
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 26, draw_id))
    assert result["entries_count"] == 1  # чек 1 + чек 2 вместе = 1 попытка

    r3 = run(sql_mgt.add_receipt(file_path="/tmp/o3.jpg", user_tg_id=26, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r3, rule_id, 2)
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 26, draw_id))
    assert result["entries_count"] == 2  # чек 3 сам по себе закрывает ещё один комплект


def test_evaluate_standard_progress_entries_count_has_no_upper_limit(mem_db):
    """Явный regression-guard на отсутствие ограничения числа попыток (владелец подтвердил:
    "10 и больше... ограничений нет, просто шансы выше") — нет ни LIMIT в SQL, ни искусственного
    потолка в подсчёте. min_quantity=1, поэтому каждый чек сразу закрывает свой комплект."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=1)
    receipt_count = 15
    for i in range(receipt_count):
        r = run(sql_mgt.add_receipt(
            file_path=f"/tmp/many_{i}.jpg", user_tg_id=50, status="Подтверждён", draw_id=draw_id,
        ))
        _insert_receipt_item(mem_db, r, rule_id, 1)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 50, draw_id))
    assert result["entries_count"] == receipt_count


def test_evaluate_standard_progress_multiple_rules_bottleneck_limits_entries(mem_db):
    """Несколько правил — число комплектов ограничено самым дефицитным (аналог "сколько
    раз можно собрать рецепт"): 4 шт. правила A (min 2 → 2 комплекта) но только 1 шт.
    правила B (min 1 → 1 комплект) — итог 1 попытка, не 2."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_a = _insert_rule(mem_db, stage_id, title="Водка", min_quantity=2)
    rule_b = _insert_rule(mem_db, stage_id, title="Джин", min_quantity=1)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/bn1.jpg", user_tg_id=27, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_a, 4)
    r2 = run(sql_mgt.add_receipt(file_path="/tmp/bn2.jpg", user_tg_id=27, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r2, rule_b, 1)
    stage = {"id": stage_id}
    result = run(sql_mgt.evaluate_standard_stage_progress(stage, 27, draw_id))
    assert result["entries_count"] == 1


# ---------------------------------------------------------------------------
# get_stage_progress — батч-версия прогресса по всем пользователям этапа
# ---------------------------------------------------------------------------

def test_get_stage_progress_empty_when_no_rules(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    assert run(sql_mgt.get_stage_progress(stage_id)) == []


def test_get_stage_progress_empty_when_rules_but_no_matches_yet(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    _insert_rule(mem_db, stage_id, min_quantity=1)
    assert run(sql_mgt.get_stage_progress(stage_id)) == []


def test_get_stage_progress_single_user_partial(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=3)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/g1.jpg", user_tg_id=30, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 2)
    progress = run(sql_mgt.get_stage_progress(stage_id))
    assert len(progress) == 1
    assert progress[0]["user_tg_id"] == 30
    assert progress[0]["complete"] is False
    assert progress[0]["rule_progress"][0]["progress"] == 2.0
    assert progress[0]["entry_receipt_ids"] == [r1]
    assert progress[0]["entries_count"] == 0  # 2 из 3 — комплект ещё не собран


def test_get_stage_progress_multiple_users_mixed_states(mem_db):
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, title="Настойка", min_quantity=2)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/g2.jpg", user_tg_id=31, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r1, rule_id, 2)
    r2 = run(sql_mgt.add_receipt(file_path="/tmp/g3.jpg", user_tg_id=32, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, r2, rule_id, 1)
    progress = {p["user_tg_id"]: p for p in run(sql_mgt.get_stage_progress(stage_id))}
    assert progress[31]["complete"] is True
    assert progress[32]["complete"] is False


def test_get_stage_progress_entry_receipt_ids_excludes_unrelated_confirmed_receipt(mem_db):
    """entry_receipt_ids (используется api_determine_winners() для выбора чека-представителя)
    не должен включать подтверждённый чек, у которого нет ни одной позиции, сматченной на
    правило ЭТОГО этапа — иначе не связанный с этапом чек мог бы "представлять" билет."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=1)
    matched = run(sql_mgt.add_receipt(file_path="/tmp/m1.jpg", user_tg_id=24, status="Подтверждён", draw_id=draw_id))
    _insert_receipt_item(mem_db, matched, rule_id, 1)
    run(sql_mgt.add_receipt(file_path="/tmp/m2.jpg", user_tg_id=24, status="Подтверждён", draw_id=draw_id))
    progress = run(sql_mgt.get_stage_progress(stage_id))
    row = next(p for p in progress if p["user_tg_id"] == 24)
    assert row["entry_receipt_ids"] == [matched]


def test_get_stage_progress_scoped_to_draw(mem_db):
    draw_id = _insert_draw(mem_db)
    other_draw_id = _insert_draw(mem_db, title="Other draw")
    stage_id = _insert_stage(mem_db, draw_id, stage_type="standard")
    other_stage_id = _insert_stage(mem_db, other_draw_id, stage_type="standard")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=1)
    other_rule_id = _insert_rule(mem_db, other_stage_id, min_quantity=1)
    r1 = run(sql_mgt.add_receipt(file_path="/tmp/g4.jpg", user_tg_id=40, status="Подтверждён", draw_id=other_draw_id))
    _insert_receipt_item(mem_db, r1, other_rule_id, 1)
    assert run(sql_mgt.get_stage_progress(stage_id)) == []


# ---------------------------------------------------------------------------
# add_manual_receipt_item (раздел 4.7 ТЗ) — добавление, не перезапись
# ---------------------------------------------------------------------------

def test_add_manual_receipt_item_does_not_erase_existing(mem_db):
    rid = run(sql_mgt.add_receipt(file_path="/tmp/manual.jpg", user_tg_id=1, status="На ручной проверке"))
    run(sql_mgt.save_receipt_items(rid, [
        {"raw_name": "FNS item", "quantity": 1, "price": 100, "sum": 100, "matched_rule_id": None},
    ]))
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id, stage_type="guaranteed_prize")
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=2)

    run(sql_mgt.add_manual_receipt_item(rid, rule_id, 2))
    items = run(sql_mgt.get_receipt_items(rid))
    assert len(items) == 2
    assert any(i["raw_name"] == "FNS item" for i in items)
    assert any(i["matched_rule_id"] == rule_id and i["quantity"] == 2 for i in items)


def test_add_manual_receipt_item_quantity_optional(mem_db):
    rid = run(sql_mgt.add_receipt(file_path="/tmp/manual2.jpg", user_tg_id=1, status="На ручной проверке"))
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id)
    rule_id = _insert_rule(mem_db, stage_id, min_quantity=1)
    run(sql_mgt.add_manual_receipt_item(rid, rule_id, None))
    items = run(sql_mgt.get_receipt_items(rid))
    assert len(items) == 1
    assert items[0]["quantity"] is None


# ---------------------------------------------------------------------------
# migrate_prize_draw_rules_draw_to_stage (раздел 4.2 ТЗ) — критичная одноразовая миграция
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_db_old_rules_schema(monkeypatch):
    """Как mem_db, но prize_draw_rules создаётся по СТАРОЙ схеме (draw_id), имитируя
    прод-БД до этой доработки — для теста автомиграции на реалистичных данных."""
    schema_path = Path(__file__).resolve().parents[1] / "table_shem.json"
    with open(schema_path) as fh:
        schema = json.load(fh)

    db_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    db_file.close()

    conn = sqlite3.connect(db_file.name)
    for table_name, ddl in schema.items():
        if table_name == "prize_draw_rules":
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prize_draw_rules "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, draw_id INTEGER NOT NULL, title TEXT NOT NULL, "
                "sku_code TEXT, aliases TEXT NOT NULL, min_quantity INTEGER DEFAULT 1, "
                "is_active BOOLEAN DEFAULT TRUE, create_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        else:
            conn.execute("CREATE TABLE IF NOT EXISTS " + ddl)
    conn.commit()
    conn.close()

    original = sql_mgt.db_name
    monkeypatch.setattr(sql_mgt, "db_name", db_file.name)
    yield db_file.name
    monkeypatch.setattr(sql_mgt, "db_name", original)
    os.unlink(db_file.name)


def _insert_old_rule(db_path, draw_id, title="Old rule", aliases="finsky", min_quantity=1, is_active=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_rules (draw_id, title, sku_code, aliases, min_quantity, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (draw_id, title, None, aliases, min_quantity, is_active),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


async def _run_migration(db_path):
    conn = await aiosqlite.connect(db_path)
    try:
        await sql_mgt.migrate_prize_draw_rules_draw_to_stage(conn)
    finally:
        await conn.close()


def test_migration_single_stage_all_rules_moved(mem_db_old_rules_schema):
    draw_id = _insert_draw(mem_db_old_rules_schema)
    stage_id = _insert_stage(mem_db_old_rules_schema, draw_id, name="Only stage")
    _insert_old_rule(mem_db_old_rules_schema, draw_id, title="Rule 1")
    _insert_old_rule(mem_db_old_rules_schema, draw_id, title="Rule 2")

    run(_run_migration(mem_db_old_rules_schema))

    rules = run(sql_mgt.get_stage_rules(stage_id, only_active=False))
    titles = sorted(r["title"] for r in rules)
    assert titles == ["Rule 1", "Rule 2"]
    # схема реально сменилась на stage_id
    columns = sql_mgt.get_table_schema_columns("prize_draw_rules")  # схема из table_shem.json, не БД — просто sanity
    conn = sqlite3.connect(mem_db_old_rules_schema)
    db_columns = {row[1] for row in conn.execute("PRAGMA table_info(prize_draw_rules)")}
    conn.close()
    assert "stage_id" in db_columns
    assert "draw_id" not in db_columns


def test_migration_two_stages_rule_duplicated(mem_db_old_rules_schema):
    draw_id = _insert_draw(mem_db_old_rules_schema)
    stage_a = _insert_stage(mem_db_old_rules_schema, draw_id, name="A", order_index=0)
    stage_b = _insert_stage(mem_db_old_rules_schema, draw_id, name="B", order_index=1)
    _insert_old_rule(mem_db_old_rules_schema, draw_id, title="Shared rule")

    run(_run_migration(mem_db_old_rules_schema))

    rules_a = run(sql_mgt.get_stage_rules(stage_a, only_active=False))
    rules_b = run(sql_mgt.get_stage_rules(stage_b, only_active=False))
    assert len(rules_a) == 1 and rules_a[0]["title"] == "Shared rule"
    assert len(rules_b) == 1 and rules_b[0]["title"] == "Shared rule"
    assert rules_a[0]["id"] != rules_b[0]["id"]


def test_migration_zero_stages_rule_skipped_with_warning(mem_db_old_rules_schema, caplog):
    draw_id = _insert_draw(mem_db_old_rules_schema)
    _insert_old_rule(mem_db_old_rules_schema, draw_id, title="Orphan rule")

    with caplog.at_level("WARNING"):
        run(_run_migration(mem_db_old_rules_schema))

    conn = sqlite3.connect(mem_db_old_rules_schema)
    count = conn.execute("SELECT COUNT(*) FROM prize_draw_rules").fetchone()[0]
    conn.close()
    assert count == 0
    assert any("Orphan rule" in rec.message or "draw_id=%s" in rec.msg for rec in caplog.records)


def test_migration_is_idempotent(mem_db_old_rules_schema):
    draw_id = _insert_draw(mem_db_old_rules_schema)
    stage_id = _insert_stage(mem_db_old_rules_schema, draw_id)
    _insert_old_rule(mem_db_old_rules_schema, draw_id, title="Rule X")

    run(_run_migration(mem_db_old_rules_schema))
    first_pass = run(sql_mgt.get_stage_rules(stage_id, only_active=False))
    assert len(first_pass) == 1

    run(_run_migration(mem_db_old_rules_schema))  # повторный запуск — no-op
    second_pass = run(sql_mgt.get_stage_rules(stage_id, only_active=False))
    assert len(second_pass) == 1
    assert second_pass[0]["id"] == first_pass[0]["id"]


def test_migration_leaves_new_schema_untouched(mem_db):
    """На новой (уже мигрированной) БД функция должна быть no-op, без ошибок."""
    draw_id = _insert_draw(mem_db)
    stage_id = _insert_stage(mem_db, draw_id)
    _insert_rule(mem_db, stage_id, title="Already on stage_id")
    run(_run_migration(mem_db))
    rules = run(sql_mgt.get_stage_rules(stage_id, only_active=False))
    assert len(rules) == 1


# ---------------------------------------------------------------------------
# save_receipt_items / get_receipt_items
# ---------------------------------------------------------------------------

def test_save_and_get_receipt_items(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/items.jpg",
        user_tg_id=1,
        status="не подтвержден",
    ))
    run(sql_mgt.save_receipt_items(rid, [
        {"raw_name": "Водка Finsky", "quantity": 2.0, "price": 500.0, "sum": 1000.0, "matched_rule_id": 1},
    ]))
    items = run(sql_mgt.get_receipt_items(rid))
    assert len(items) == 1
    assert items[0]["raw_name"] == "Водка Finsky"
    assert items[0]["quantity"] == 2.0
    assert items[0]["matched_rule_id"] == 1


def test_save_receipt_items_clears_previous_rows(mem_db):
    rid = run(sql_mgt.add_receipt(
        file_path="/tmp/items2.jpg",
        user_tg_id=1,
        status="не подтвержден",
    ))
    run(sql_mgt.save_receipt_items(rid, [{"raw_name": "A", "quantity": 1, "price": 1, "sum": 1, "matched_rule_id": None}]))
    run(sql_mgt.save_receipt_items(rid, [{"raw_name": "B", "quantity": 2, "price": 2, "sum": 4, "matched_rule_id": None}]))
    items = run(sql_mgt.get_receipt_items(rid))
    assert len(items) == 1
    assert items[0]["raw_name"] == "B"


def test_get_receipt_items_empty_for_unknown_receipt(mem_db):
    assert run(sql_mgt.get_receipt_items(999999)) == []


class TestGetNextMonthDate:
    def test_normal_month_increment(self):
        result = sql_mgt.get_next_month_date(date(2025, 3, 15))
        assert result.month == 4
        assert result.year == 2025

    def test_december_wraps_to_january(self):
        result = sql_mgt.get_next_month_date(date(2025, 12, 15))
        assert result.month == 1
        assert result.year == 2026

    def test_day_above_28_resets_to_1(self):
        result = sql_mgt.get_next_month_date(date(2025, 1, 31))
        assert result.day == 1

    def test_day_28_or_below_preserved(self):
        result = sql_mgt.get_next_month_date(date(2025, 1, 15))
        assert result.day == 15
