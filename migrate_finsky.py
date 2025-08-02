import sqlite3
import sys
import os
from keys import DB_NAME


def get_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def get_columns(conn, table):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def load_source_db(sql_path):
    conn = sqlite3.connect(':memory:')
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    conn.executescript(sql)
    conn.commit()
    return conn


def migrate_data(source_conn, dest_conn):
    src_tables = get_tables(source_conn)
    dest_tables = get_tables(dest_conn)
    common_tables = src_tables & dest_tables

    for table in common_tables:
        src_cols = get_columns(source_conn, table)
        dest_cols = get_columns(dest_conn, table)
        shared_cols = [c for c in src_cols if c in dest_cols]
        if not shared_cols:
            continue
        placeholder = ','.join(['?'] * len(shared_cols))
        cols_joined = ','.join(shared_cols)
        rows = source_conn.execute(
            f"SELECT {cols_joined} FROM {table}"
        ).fetchall()
        if rows:
            dest_conn.executemany(
                f"INSERT OR REPLACE INTO {table} ({cols_joined}) VALUES ({placeholder})",
                rows,
            )
    dest_conn.commit()


def main():
    if len(sys.argv) < 2:
        print('Usage: python migrate_finsky.py <finsky.sql> [dest_db]')
        sys.exit(1)
    sql_path = sys.argv[1]
    dest_db = sys.argv[2] if len(sys.argv) > 2 else DB_NAME

    if not os.path.isfile(sql_path):
        raise FileNotFoundError(sql_path)

    source_conn = load_source_db(sql_path)
    dest_conn = sqlite3.connect(dest_db)

    try:
        migrate_data(source_conn, dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()


if __name__ == '__main__':
    main()
