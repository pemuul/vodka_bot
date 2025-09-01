"""
Конвертация SQL-дампа в базу данных SQLite.

Как использовать:
    python sql_dump_to_sqlite.py путь_к_дампу.sql путь_к_базе.db

Скрипт создаст новую базу SQLite, выполнит совместимые инструкции из файла
дампа и сохранит в текущей папке файл ``original_schema.sql`` с описанием
таблиц исходной базы.
"""

import argparse
import sqlite3
import re
from pathlib import Path

def convert(dump_path: str, db_path: str) -> None:
    dump = Path(dump_path)
    if not dump.exists():
        raise FileNotFoundError(f"Не найден файл дампа: {dump_path}")

    schema_lines = []

    with sqlite3.connect(db_path) as conn, dump.open("r", encoding="utf-8") as f:
        cur = conn.cursor()
        statement = []
        capturing = False
        skip_block = False
        for line in f:
            stripped = line.strip()
            if skip_block:
                if stripped == "\\." or stripped.endswith(";"):
                    skip_block = False
                continue
            if not stripped or stripped.startswith("--"):
                continue
            upper = stripped.upper()
            if upper.startswith((
                "SET ",
                "SELECT ",
                "LOCK ",
                "UNLOCK ",
                "DELIMITER ",
            )) or " OWNER TO " in upper or upper.startswith("COMMENT ON") or upper.startswith("REVOKE") or upper.startswith("GRANT"):
                continue
            if upper.startswith("CREATE INDEX") or upper.startswith("CREATE UNIQUE INDEX") or upper.startswith("DROP INDEX"):
                continue
            if upper.startswith("ALTER TABLE"):
                skip_block = True
                statement = []
                continue
            if upper.startswith("COPY "):
                skip_block = True
                statement = []
                continue
            if upper.startswith("CREATE SEQUENCE") or upper.startswith("ALTER SEQUENCE"):
                skip_block = True
                statement = []
                continue
            if upper.startswith("CREATE TABLE"):
                capturing = True
            if capturing:
                schema_lines.append(line)
                if stripped.endswith(";"):
                    capturing = False
            line = re.sub(r"\bpublic\.", "", line, flags=re.IGNORECASE)
            line = re.sub(r"\bWITHOUT TIME ZONE\b", "", line, flags=re.IGNORECASE)
            statement.append(line)
            if stripped.endswith(";"):
                cur.executescript("".join(statement))
                statement = []

    Path("original_schema.sql").write_text("".join(schema_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Импортировать SQL-дамп в SQLite базу")
    parser.add_argument("dump", help="Путь к .sql файлу")
    parser.add_argument("database", help="Путь к создаваемой базе SQLite")
    args = parser.parse_args()
    convert(args.dump, args.database)


if __name__ == "__main__":
    main()
