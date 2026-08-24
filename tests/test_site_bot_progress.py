"""Lightweight tests for the new standard-stage progress helpers in site_bot/main.py.

site_bot/main.py has no other test coverage in this project (it uses databases/SQLAlchemy,
not aiosqlite, and there's no existing HTTP/TestClient test infrastructure for it — see
CLAUDE.md). This file intentionally covers only the new pure-DB helper functions directly,
by calling them as plain async functions against a real temp SQLite DB — no HTTP layer.
This is a deliberately narrower scope than tests/test_sql_mgt.py's equivalent coverage,
per the project owner's explicit decision for this change ("лёгкое покрытие новых функций
напрямую").

site_bot/main.py's module-level `Database(DATABASE_URL)`/`create_engine(...)` bind to
VODKA_DB_PATH at IMPORT time, so the env var must be set before the module is first
imported — the fixture below deletes any cached import and re-imports fresh.
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def site_bot_main(monkeypatch):
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

    monkeypatch.setenv("VODKA_DB_PATH", db_file.name)
    monkeypatch.setenv("TG_BOT", "0:dummy-token-for-tests")
    for mod_name in list(sys.modules):
        if mod_name == "site_bot" or mod_name.startswith("site_bot."):
            del sys.modules[mod_name]

    # main.py mounts StaticFiles(directory="static") at import time, relative to CWD (in
    # production it's always run with cwd=site_bot/, per CLAUDE.md's supervisor config).
    site_bot_dir = Path(__file__).resolve().parents[1] / "site_bot"
    monkeypatch.chdir(site_bot_dir)
    import site_bot.main as main_module

    run(main_module.database.connect())
    try:
        yield db_file.name, main_module
    finally:
        run(main_module.database.disconnect())
        os.unlink(db_file.name)


def _insert_draw(db_path, title="Test draw"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("INSERT INTO prize_draws (title) VALUES (?)", (title,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_stage(db_path, draw_id, name="Этап", stage_type="standard"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_stages (draw_id, name, stage_type) VALUES (?, ?, ?)",
            (draw_id, name, stage_type),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_rule(db_path, stage_id, title="Настойка", aliases="настойка", min_quantity=1):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prize_draw_rules (stage_id, title, aliases, min_quantity) "
            "VALUES (?, ?, ?, ?)",
            (stage_id, title, aliases, min_quantity),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_receipt_with_item(db_path, draw_id, user_tg_id, rule_id, quantity, status="Подтверждён"):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO receipts (file_path, user_tg_id, draw_id, status) VALUES (?, ?, ?, ?)",
            (f"/tmp/{user_tg_id}.jpg", user_tg_id, draw_id, status),
        )
        receipt_id = cur.lastrowid
        conn.execute(
            "INSERT INTO receipt_items (receipt_id, raw_name, quantity, price, sum, matched_rule_id) "
            "VALUES (?, 'test item', ?, NULL, NULL, ?)",
            (receipt_id, quantity, rule_id),
        )
        conn.commit()
        return receipt_id
    finally:
        conn.close()


def _insert_confirmed_receipt_unrelated(db_path, draw_id, user_tg_id, matched_rule_id=None):
    """A confirmed receipt that has NO connection to the stage's rules — either no items at
    all, or an item matched to a rule belonging to a DIFFERENT stage. Used to prove such
    receipts must not count as raffle entries for this stage."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO receipts (file_path, user_tg_id, draw_id, status) VALUES (?, ?, ?, 'Подтверждён')",
            (f"/tmp/unrelated_{user_tg_id}_{matched_rule_id}.jpg", user_tg_id, draw_id),
        )
        receipt_id = cur.lastrowid
        if matched_rule_id is not None:
            conn.execute(
                "INSERT INTO receipt_items (receipt_id, raw_name, quantity, price, sum, matched_rule_id) "
                "VALUES (?, 'unrelated item', 1, NULL, NULL, ?)",
                (receipt_id, matched_rule_id),
            )
        conn.commit()
        return receipt_id
    finally:
        conn.close()


def _insert_user(db_path, tg_id, name="Тест Юзер"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO users (tg_id, name) VALUES (?, ?)", (tg_id, name))
        conn.commit()
    finally:
        conn.close()


class TestEvaluateStandardStageProgress:
    def test_no_rules(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        stage = run(main_module.database.fetch_one(
            main_module.prize_draw_stages_table.select().where(
                main_module.prize_draw_stages_table.c.id == stage_id
            )
        ))
        result = run(main_module._evaluate_standard_stage_progress(dict(stage), 1, draw_id))
        assert result == {"outcome": "no_rules"}

    def test_progress_not_yet_complete(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=3)
        _insert_receipt_with_item(db_path, draw_id, 10, rule_id, 2)
        stage = {"id": stage_id}
        result = run(main_module._evaluate_standard_stage_progress(stage, 10, draw_id))
        assert result["outcome"] == "progress"
        assert result["rule_progress"][0]["progress"] == 2.0

    def test_complete_never_writes_winner(self, site_bot_main):
        """Regression guard mirroring sql_mgt's equivalent test: standard stages must never
        auto-win, even from the web-side duplicate implementation."""
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        _insert_receipt_with_item(db_path, draw_id, 11, rule_id, 1)
        stage = {"id": stage_id}
        result = run(main_module._evaluate_standard_stage_progress(stage, 11, draw_id))
        assert result["outcome"] == "complete"
        assert run(main_module._is_stage_winner(stage_id, 11)) is False

    def test_entries_count_with_min_quantity_one_matches_receipt_count(self, site_bot_main):
        """При min_quantity=1 каждый чек сразу закрывает свой комплект, поэтому число
        попыток совпадает с числом чеков — частный случай, не общее правило (см. следующий
        тест, где это не так)."""
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        _insert_receipt_with_item(db_path, draw_id, 12, rule_id, 1)
        _insert_receipt_with_item(db_path, draw_id, 12, rule_id, 1)
        stage = {"id": stage_id}
        result = run(main_module._evaluate_standard_stage_progress(stage, 12, draw_id))
        assert result["outcome"] == "complete"
        assert result["entries_count"] == 2

    def test_entries_count_is_sets_not_receipts(self, site_bot_main):
        """Уточнение владельца: "не просто каждый чек, а группа чеков от 1 и более в
        совокупности проходящая валидацию". min_quantity=2: два чека по 1 шт. вместе дают
        РОВНО 1 попытку, не 2."""
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=2)
        _insert_receipt_with_item(db_path, draw_id, 14, rule_id, 1)
        _insert_receipt_with_item(db_path, draw_id, 14, rule_id, 1)
        stage = {"id": stage_id}
        result = run(main_module._evaluate_standard_stage_progress(stage, 14, draw_id))
        assert result["outcome"] == "complete"
        assert result["entries_count"] == 1

    def test_entries_count_excludes_unrelated_confirmed_receipts(self, site_bot_main):
        """Чек, подтверждённый, но не сматченный ни на одно правило ЭТОГО этапа, не должен
        влиять на прогресс/попытки — иначе счётчик, который видит пользователь, завысится."""
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        _insert_receipt_with_item(db_path, draw_id, 13, rule_id, 1)
        _insert_confirmed_receipt_unrelated(db_path, draw_id, 13)
        stage = {"id": stage_id}
        result = run(main_module._evaluate_standard_stage_progress(stage, 13, draw_id))
        assert result["entries_count"] == 1


class TestGetStageProgress:
    def test_empty_when_no_rules(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        assert run(main_module._get_stage_progress(stage_id)) == []

    def test_multiple_users_mixed_states(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=2)
        _insert_receipt_with_item(db_path, draw_id, 20, rule_id, 2)
        _insert_receipt_with_item(db_path, draw_id, 21, rule_id, 1)
        progress = {p["user_tg_id"]: p for p in run(main_module._get_stage_progress(stage_id))}
        assert progress[20]["complete"] is True
        assert progress[21]["complete"] is False

    def test_ignores_unconfirmed_receipts(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        _insert_receipt_with_item(db_path, draw_id, 22, rule_id, 5, status="На ручной проверке")
        assert run(main_module._get_stage_progress(stage_id)) == []

    def test_entry_receipt_ids_exclude_unrelated_receipts(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        matched_id = _insert_receipt_with_item(db_path, draw_id, 23, rule_id, 1)
        _insert_confirmed_receipt_unrelated(db_path, draw_id, 23)
        progress = run(main_module._get_stage_progress(stage_id))
        row = next(p for p in progress if p["user_tg_id"] == 23)
        assert row["entry_receipt_ids"] == [matched_id]
        assert row["entries_count"] == 1


class TestApiDetermineWinnersEntryScoping:
    """Regression coverage for the win-calculation correctness check the owner asked for:
    a complete user's raffle entries must be exactly the receipts matched to THIS stage's
    rules, not every confirmed receipt they have in the draw. api_determine_winners() has
    no FastAPI Depends()-based parameters, so it's directly callable as a plain coroutine —
    no HTTP/TestClient layer needed for this."""

    def test_unrelated_confirmed_receipt_is_not_an_entry(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        _insert_user(db_path, 30, "Победитель")

        matched_id = _insert_receipt_with_item(db_path, draw_id, 30, rule_id, 1)
        unrelated_id = _insert_confirmed_receipt_unrelated(db_path, draw_id, 30)

        result = run(main_module.api_determine_winners(
            stage_id, main_module.DetermineReq(winners_count=5)
        ))
        winners = result["winners"]
        assert len(winners) == 1
        assert winners[0]["receipt_id"] == matched_id
        assert winners[0]["receipt_id"] != unrelated_id

    def test_incomplete_user_gets_no_entries_even_with_confirmed_receipts(self, site_bot_main):
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=3)
        _insert_user(db_path, 31, "Недобравший")
        _insert_receipt_with_item(db_path, draw_id, 31, rule_id, 1)

        with pytest.raises(Exception):
            run(main_module.api_determine_winners(
                stage_id, main_module.DetermineReq(winners_count=1)
            ))

    def test_multiple_entries_for_same_user_all_eligible(self, site_bot_main):
        """Чем больше накоплено комплектов (entries_count) — тем больше билетов в пуле для
        этого пользователя, что и реализует "чем больше чеков, тем больше шанс". При
        min_quantity=1 три чека по 1 шт. дают 3 комплекта → 3 билета — но билеты не
        привязаны 1:1 к конкретным чекам (комплект мог бы собраться и из нескольких), так
        что все билеты одного пользователя в пуле указывают на один и тот же
        чек-представитель, а не на три разных."""
        db_path, main_module = site_bot_main
        draw_id = _insert_draw(db_path)
        stage_id = _insert_stage(db_path, draw_id)
        rule_id = _insert_rule(db_path, stage_id, min_quantity=1)
        _insert_user(db_path, 32, "Активный")
        r1 = _insert_receipt_with_item(db_path, draw_id, 32, rule_id, 1)
        r2 = _insert_receipt_with_item(db_path, draw_id, 32, rule_id, 1)
        r3 = _insert_receipt_with_item(db_path, draw_id, 32, rule_id, 1)

        result = run(main_module.api_determine_winners(
            stage_id, main_module.DetermineReq(winners_count=10)
        ))
        winners = result["winners"]
        assert len(winners) == 3
        assert all(w["user_id"] == 32 for w in winners)
        receipt_ids = {w["receipt_id"] for w in winners}
        assert receipt_ids <= {r1, r2, r3}
        assert len(receipt_ids) == 1  # один представитель на все билеты этого пользователя
