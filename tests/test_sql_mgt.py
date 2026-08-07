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
    def test_prize_draws_has_auto_validation_column(self):
        columns = sql_mgt.get_table_schema_columns("prize_draws")
        col_dict = dict(columns)
        assert "auto_validation_enabled" in col_dict
        assert "DEFAULT 1" in col_dict["auto_validation_enabled"]

    def test_prize_draw_rules_schema(self):
        columns = sql_mgt.get_table_schema_columns("prize_draw_rules")
        names = [c[0] for c in columns]
        for expected in ("id", "draw_id", "title", "sku_code", "aliases", "min_quantity", "is_active"):
            assert expected in names, f"Expected column '{expected}' in prize_draw_rules"

    def test_receipt_items_schema(self):
        columns = sql_mgt.get_table_schema_columns("receipt_items")
        names = [c[0] for c in columns]
        for expected in ("id", "receipt_id", "raw_name", "quantity", "price", "sum", "matched_rule_id"):
            assert expected in names, f"Expected column '{expected}' in receipt_items"


# ---------------------------------------------------------------------------
# get_draw_auto_validation
# ---------------------------------------------------------------------------

def _insert_draw(db_path, status="active", auto_validation_enabled=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draws (title, start_date, end_date, status, auto_validation_enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Test draw", "2020-01-01", "2999-01-01", status, auto_validation_enabled),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_get_draw_auto_validation_none_draw_id_defaults_true(mem_db):
    assert run(sql_mgt.get_draw_auto_validation(None)) is True


def test_get_draw_auto_validation_enabled(mem_db):
    draw_id = _insert_draw(mem_db, auto_validation_enabled=1)
    assert run(sql_mgt.get_draw_auto_validation(draw_id)) is True


def test_get_draw_auto_validation_disabled(mem_db):
    draw_id = _insert_draw(mem_db, auto_validation_enabled=0)
    assert run(sql_mgt.get_draw_auto_validation(draw_id)) is False


def test_get_draw_auto_validation_null_defaults_true(mem_db):
    draw_id = _insert_draw(mem_db, auto_validation_enabled=1)
    conn = sqlite3.connect(mem_db)
    conn.execute("UPDATE prize_draws SET auto_validation_enabled = NULL WHERE id = ?", (draw_id,))
    conn.commit()
    conn.close()
    assert run(sql_mgt.get_draw_auto_validation(draw_id)) is True


# ---------------------------------------------------------------------------
# get_draw_rules
# ---------------------------------------------------------------------------

def _insert_rule(db_path, draw_id, title="Финская водка", aliases="finsky;фински", min_quantity=1, is_active=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_rules (draw_id, title, sku_code, aliases, min_quantity, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (draw_id, title, "finsky-vodka", aliases, min_quantity, is_active),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_get_draw_rules_empty_when_none(mem_db):
    draw_id = _insert_draw(mem_db)
    assert run(sql_mgt.get_draw_rules(draw_id)) == []


def test_get_draw_rules_returns_active_only(mem_db):
    draw_id = _insert_draw(mem_db)
    _insert_rule(mem_db, draw_id, title="Active rule", is_active=1)
    _insert_rule(mem_db, draw_id, title="Inactive rule", is_active=0)
    rules = run(sql_mgt.get_draw_rules(draw_id))
    assert len(rules) == 1
    assert rules[0]["title"] == "Active rule"


def test_get_draw_rules_only_active_false_returns_all(mem_db):
    draw_id = _insert_draw(mem_db)
    _insert_rule(mem_db, draw_id, title="Active rule", is_active=1)
    _insert_rule(mem_db, draw_id, title="Inactive rule", is_active=0)
    rules = run(sql_mgt.get_draw_rules(draw_id, only_active=False))
    assert len(rules) == 2


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
