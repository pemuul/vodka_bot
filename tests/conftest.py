"""Shared fixtures for the test suite."""

import sys
import os
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Ensure the project root is on sys.path so imports like `import sql_mgt` work.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path) -> Generator[str, None, None]:
    """Return a path to a fresh SQLite database pre-populated with the project schema."""
    import sql_mgt

    db_path = str(tmp_path / "test.sqlite")
    table_shem_path = PROJECT_ROOT / "table_shem.json"
    with open(table_shem_path) as fh:
        schema = json.load(fh)

    with sqlite3.connect(db_path) as conn:
        for ddl in schema.values():
            conn.execute("CREATE TABLE IF NOT EXISTS " + ddl)
        conn.commit()

    original_db_name = sql_mgt.db_name
    sql_mgt.db_name = db_path
    try:
        yield db_path
    finally:
        sql_mgt.db_name = original_db_name


@pytest.fixture()
def event_loop():
    """Provide a fresh event loop per test (compatible with pytest-asyncio)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
