#!/usr/bin/env python3
"""
Convert a PostgreSQL plain-text dump (with CREATE TABLE + COPY) into a SQLite database,
then generate a Markdown file describing the schema with 3 sample rows per table.

Usage:
  python pgdump_to_sqlite.py input.sql output.sqlite output.md
If output.md is omitted, "<output.sqlite>_structure.md" will be created next to the DB.
"""

import sys, re, sqlite3, csv
from pathlib import Path


def transform_create_table_block(block: str) -> str:
    block = re.sub(r'CREATE TABLE\s+public\.', 'CREATE TABLE ', block, flags=re.IGNORECASE)
    def _quote_tbl(m):
        tbl = m.group(2).strip('"')
        return f'{m.group(1)}"{tbl}"'
    block = re.sub(r'(CREATE TABLE\s+)([^\s(]+)', _quote_tbl, block, count=1, flags=re.IGNORECASE)
    block = re.sub(r'ALTER TABLE .*? OWNER TO .*?;', '', block, flags=re.IGNORECASE|re.DOTALL)
    block = re.sub(r'DEFAULT\s+nextval\([^)]+\)', '', block, flags=re.IGNORECASE)
    block = re.sub(r'DEFAULT\s+true\b', 'DEFAULT 1', block, flags=re.IGNORECASE)
    block = re.sub(r'DEFAULT\s+false\b', 'DEFAULT 0', block, flags=re.IGNORECASE)
    block = re.sub(r'\bwithout time zone\b', '', block, flags=re.IGNORECASE)
    block = re.sub(r',\s*\)', ')', block, flags=re.DOTALL)
    return block


def parse_copy_header(line: str):
    m = re.match(r'COPY\s+([^\s(]+)\s*\((.*?)\)\s+FROM\s+stdin;', line, flags=re.IGNORECASE)
    if not m:
        return None, None
    raw_table = m.group(1).strip()
    if '.' in raw_table:
        table = raw_table.split('.', 1)[1]
    else:
        table = raw_table
    cols_raw = m.group(2).strip()
    cols = [c.strip().strip('"') for c in cols_raw.split(',')]
    return table, cols


def sqlite_insert(cur, table: str, cols, rows):
    if not rows:
        return
    placeholders = ','.join(['?'] * len(cols))
    cols_sql = ','.join([f'"{c}"' for c in cols])
    sql = f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders})'
    cur.executemany(sql, rows)


def escape_md(text):
    if text is None:
        return 'NULL'
    if isinstance(text, (int, float)):
        return str(text)
    s = str(text)
    if len(s) > 300:
        s = s[:297] + '...'
    s = s.replace('\n', ' ').replace('\r', ' ')
    s = s.replace('|', '\\|')
    return s


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src_sql = Path(sys.argv[1])
    out_db = Path(sys.argv[2])
    out_md = Path(sys.argv[3]) if len(sys.argv) > 3 else out_db.with_name(out_db.stem + "_structure.md")

    if out_db.exists():
        out_db.unlink()

    conn = sqlite3.connect(str(out_db))
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=OFF;")
    cur.execute("PRAGMA synchronous=OFF;")
    cur.execute("PRAGMA temp_store=MEMORY;")
    cur.execute("PRAGMA cache_size=-50000;")

    state = 'idle'
    create_block_lines = []
    copy_table = None
    copy_cols = []
    copy_rows_buffer = []

    cur.execute("BEGIN;")
    try:
        with src_sql.open('r', encoding='utf-8') as f:
            for line in f:
                raw = line.rstrip('\n')

                if state == 'idle':
                    if not raw.strip():
                        continue
                    if raw.startswith('--') or raw.upper().startswith('SET ') or raw.upper().startswith('SELECT pg_catalog'):
                        continue
                    if raw.upper().startswith('ALTER SEQUENCE') or raw.upper().startswith('CREATE SEQUENCE'):
                        continue
                    if raw.upper().startswith('ALTER TABLE') and 'OWNER TO' in raw:
                        continue
                    if raw.upper().startswith('ALTER TABLE ONLY') and 'SET DEFAULT nextval' in raw:
                        continue

                    if raw.upper().startswith('CREATE TABLE '):
                        create_block_lines = [raw]
                        state = 'in_create'
                        continue
                    if raw.upper().startswith('COPY '):
                        table, cols = parse_copy_header(raw)
                        if table is not None:
                            copy_table, copy_cols = table.strip('"'), cols
                            copy_rows_buffer = []
                            state = 'in_copy'
                            continue
                        continue

                    continue

                elif state == 'in_create':
                    create_block_lines.append(raw)
                    if raw.strip().endswith(');'):
                        block = '\n'.join(create_block_lines)
                        sql = transform_create_table_block(block)
                        cur.executescript(sql)
                        create_block_lines = []
                        state = 'idle'
                    continue

                elif state == 'in_copy':
                    if raw == r'\.':
                        sqlite_insert(cur, copy_table, copy_cols, copy_rows_buffer)
                        copy_rows_buffer = []
                        copy_table, copy_cols = None, []
                        state = 'idle'
                        continue

                    parts = raw.split('\t')
                    row = [None if p == r'\N' else p for p in parts]
                    if len(row) != len(copy_cols):
                        reader = csv.reader([raw], delimiter='\t', quoting=csv.QUOTE_MINIMAL)
                        row = next(reader)
                        row = [None if p == r'\N' else p for p in row]
                        if len(row) != len(copy_cols):
                            raise RuntimeError(f"COPY row has {len(row)} fields but expected {len(copy_cols)} for table {copy_table}. Problematic line:\n{raw}")

                    copy_rows_buffer.append(row)
                    if len(copy_rows_buffer) >= 1000:
                        sqlite_insert(cur, copy_table, copy_cols, copy_rows_buffer)
                        copy_rows_buffer = []
                    continue
        if state == 'in_copy' and copy_rows_buffer:
            sqlite_insert(cur, copy_table, copy_cols, copy_rows_buffer)
            copy_rows_buffer = []
            state = 'idle'
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Schema report
    md_lines = []
    md_lines.append(f"# SQLite структура: {out_db.name}\n")
    md_lines.append(f"_Источник: {src_sql.name}_\n")

    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;").fetchall()]

    for t in tables:
        md_lines.append(f"\n## Таблица: `{t}`\n")
        cols = cur.execute(f'PRAGMA table_info("{t}")').fetchall()
        md_lines.append("**Поля:**")
        md_lines.append("")
        md_lines.append("| # | Имя | Тип | NOT NULL | По умолчанию | PK |")
        md_lines.append("|---:|-----|-----|:--------:|--------------|:--:|")
        for cid, name, coltype, notnull, dflt_value, pk in cols:
            md_lines.append(f"| {cid} | `{name}` | `{coltype}` | {('✅' if notnull else '')} | {escape_md(dflt_value)} | {('✅' if pk else '')} |")

        try:
            cnt = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception as e:
            cnt = f"ошибка: {e}"
        md_lines.append(f"\nВсего записей: **{cnt}**\n")

        try:
            rows = cur.execute(f'SELECT * FROM "{t}" LIMIT 3').fetchall()
            if rows:
                headers = [c[1] for c in cols]
                md_lines.append("\nПримеры записей (до 3):\n")
                md_lines.append("| " + " | ".join(f"`{h}`" for h in headers) + " |")
                md_lines.append("|" + "|".join(["---"] * len(headers)) + "|")
                for r in rows:
                    md_lines.append("| " + " | ".join(escape_md(v) for v in r) + " |")
            else:
                md_lines.append("\nПримеры записей: _нет данных_")
        except Exception as e:
            md_lines.append(f"\nПримеры записей: ошибка выборки — {e}")

    out_md.write_text("\n".join(md_lines), encoding='utf-8')
    conn.close()
    print("Done.")
    print("SQLite DB:", out_db)
    print("Markdown:", out_md)


if __name__ == '__main__':
    main()
