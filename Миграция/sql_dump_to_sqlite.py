"""
Конвертация SQL-дампа в базу данных SQLite.

Как использовать:
    python sql_dump_to_sqlite.py путь_к_дампу.sql путь_к_базе.db

Скрипт создаст новую базу SQLite и выполнит все инструкции из файла дампа.
"""

import argparse
import sqlite3
from pathlib import Path

def convert(dump_path: str, db_path: str) -> None:
    dump = Path(dump_path)
    if not dump.exists():
        raise FileNotFoundError(f"Не найден файл дампа: {dump_path}")
    with sqlite3.connect(db_path) as conn, dump.open("r", encoding="utf-8") as f:
        sql_script = f.read()
        conn.executescript(sql_script)


def main() -> None:
    parser = argparse.ArgumentParser(description="Импортировать SQL-дамп в SQLite базу")
    parser.add_argument("dump", help="Путь к .sql файлу")
    parser.add_argument("database", help="Путь к создаваемой базе SQLite")
    args = parser.parse_args()
    convert(args.dump, args.database)


if __name__ == "__main__":
    main()
