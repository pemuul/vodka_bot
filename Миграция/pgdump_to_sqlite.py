#!/usr/bin/env python3
"""
Конвертирует плоский дамп PostgreSQL (CREATE TABLE + COPY FROM stdin) в SQLite
и формирует Markdown-отчёт о схеме с 3 примерами строк на таблицу.

Использование:
  python pgdump_to_sqlite.py input.sql output.sqlite [output.md]
Если output.md опущен, будет создан файл "<output.sqlite>_structure.md".

python pgdump_to_sqlite.py finsky.sql output.sqlite [output.md]
python pgdump_to_sqlite.py finsky-20251119020001.sql output.sqlite

"""

import sys, re, sqlite3, csv
from pathlib import Path

# ---------------- helpers for DDL ----------------

_PG_TO_SQLITE_TYPES = [
    (re.compile(r'\b(bigserial|serial8)\b', re.I), 'INTEGER'),
    (re.compile(r'\bserial\b', re.I), 'INTEGER'),
    (re.compile(r'\bbigint\b', re.I), 'INTEGER'),
    (re.compile(r'\binteger\b', re.I), 'INTEGER'),
    (re.compile(r'\bsmallint\b', re.I), 'INTEGER'),
    (re.compile(r'\bdouble\s+precision\b', re.I), 'REAL'),
    (re.compile(r'\bnumeric\([^)]+\)\b', re.I), 'REAL'),
    (re.compile(r'\bnumeric\b', re.I), 'REAL'),
    (re.compile(r'\bdecimal\([^)]+\)\b', re.I), 'REAL'),
    (re.compile(r'\bdecimal\b', re.I), 'REAL'),
    (re.compile(r'\breal\b', re.I), 'REAL'),
    (re.compile(r'\bboolean\b', re.I), 'INTEGER'),
    (re.compile(r'\btimestamp\s*\([^)]+\)', re.I), 'TEXT'),
    (re.compile(r'\btimestamp\b', re.I), 'TEXT'),
    (re.compile(r'\btime\s*\([^)]+\)', re.I), 'TEXT'),
    (re.compile(r'\btime\b', re.I), 'TEXT'),
    (re.compile(r'\bdate\b', re.I), 'TEXT'),
    (re.compile(r'\bcharacter\s+varying\([^)]+\)', re.I), 'TEXT'),
    (re.compile(r'\bcharacter\s+varying\b', re.I), 'TEXT'),
    (re.compile(r'\bvarchar\([^)]+\)', re.I), 'TEXT'),
    (re.compile(r'\bvarchar\b', re.I), 'TEXT'),
    (re.compile(r'\btext\b', re.I), 'TEXT'),
    (re.compile(r'\bjsonb?\b', re.I), 'TEXT'),
]

def _replace_outside_quotes(sql: str, replacers):
    """Apply regex replacements only outside double-quoted identifiers."""
    out = []
    i = 0
    in_q = False
    buf = []
    while i < len(sql):
        ch = sql[i]
        if ch == '"':
            if in_q and i+1 < len(sql) and sql[i+1] == '"':
                # escaped double quote inside identifier
                out.append('""')
                i += 2
                continue
            if not in_q:
                # flush pending buffer with replacements
                seg = ''.join(buf)
                for rx, to in replacers:
                    seg = rx.sub(to, seg)
                out.append(seg)
                buf = []
                out.append('"')
                in_q = True
            else:
                out.append('"')
                in_q = False
            i += 1
        else:
            if in_q:
                out.append(ch)
            else:
                buf.append(ch)
            i += 1
    if buf:
        seg = ''.join(buf)
        for rx, to in replacers:
            seg = rx.sub(to, seg)
        out.append(seg)
    return ''.join(out)

def _quote_table_name(sql: str) -> str:
    # ensure CREATE TABLE <name> is quoted and without schema
    def _repl(m):
        left = m.group(1)
        name = m.group(2)
        name = name.split('.', 1)[-1]  # drop schema if any
        name = name.strip('"')
        return f'{left}"{name}"'
    return re.sub(r'(CREATE\s+TABLE\s+)([^\s(]+)', _repl, sql, count=1, flags=re.I)

def transform_create_table_block(block: str) -> str:
    # remove schema qualifier
    block = re.sub(r'CREATE\s+TABLE\s+public\.', 'CREATE TABLE ', block, flags=re.I)
    block = _quote_table_name(block)

    # drop OWNER/nextval specifics if they occasionally leak in the block
    block = re.sub(r'ALTER\s+TABLE\s+.*?OWNER\s+TO\s+.*?;', '', block, flags=re.I|re.S)
    block = re.sub(r'DEFAULT\s+nextval\([^)]+\)', '', block, flags=re.I)

    # booleans
    block = re.sub(r'\bDEFAULT\s+true\b', 'DEFAULT 1', block, flags=re.I)
    block = re.sub(r'\bDEFAULT\s+false\b', 'DEFAULT 0', block, flags=re.I)

    # time zone wording
    block = re.sub(r'\bwithout\s+time\s+zone\b', '', block, flags=re.I)

    # map types only outside quoted identifiers
    block = _replace_outside_quotes(block, _PG_TO_SQLITE_TYPES)

    # trailing comma before ')'
    block = re.sub(r',\s*\)', ')', block, flags=re.S)

    return block

# ---------------- helpers for COPY ----------------

def parse_copy_header(line: str):
    # COPY schema.table (a,b,c) FROM stdin;
    m = re.match(r'^\s*COPY\s+([^\s(]+)(?:\s*\(([^)]*)\))?\s+FROM\s+stdin;', line, flags=re.I)
    if not m:
        return None, None
    raw_table = m.group(1).strip()
    table = raw_table.split('.', 1)[-1].strip('"')
    cols_raw = (m.group(2) or '').strip()
    cols = [c.strip().strip('"') for c in cols_raw.split(',')] if cols_raw else None
    return table, cols

def decode_pg_field(s: str):
    # special NULL
    if s == r'\N':
        return None
    # unescape standard COPY text escapes
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch != '\\':
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(s):
            out.append('\\')
            break
        esc = s[i]
        i += 1
        if esc == 't': out.append('\t')
        elif esc == 'n': out.append('\n')
        elif esc == 'r': out.append('\r')
        elif esc == 'b': out.append('\b')
        elif esc == 'f': out.append('\f')
        elif esc == 'v': out.append('\v')
        else: out.append(esc)
    return ''.join(out)

def build_type_casts(cur, table: str, cols):
    """Return list of caster functions for each column based on PRAGMA table_info types."""
    info = cur.execute(f'PRAGMA table_info("{table}")').fetchall()
    type_by_name = {name: (coltype.upper() if coltype else '') for (_, name, coltype, _, _, _) in info}
    casters = []
    for c in cols:
        t = type_by_name.get(c, '')
        if 'INT' in t and 'TEXT' not in t and 'REAL' not in t:
            def to_int(x):
                if x is None or x == '': return None
                try: return int(x)
                except: return x
            casters.append(to_int)
        elif 'REAL' in t or 'DOUBLE' in t or 'NUMERIC' in t or 'DECIMAL' in t or 'FLOAT' in t:
            def to_float(x):
                if x is None or x == '': return None
                try: return float(x)
                except: return x
            casters.append(to_float)
        elif 'BOOL' in t:
            def to_bool(x):
                if x is None: return None
                if x in ('t','T','1',1,True): return 1
                if x in ('f','F','0',0,False): return 0
                return x
            casters.append(to_bool)
        else:
            casters.append(lambda x: x)
    return casters

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
    copy_cols = None
    copy_rows_buffer = []
    casters = None

    cur.execute("BEGIN;")
    try:
        with src_sql.open('r', encoding='utf-8', errors='replace', newline='') as f:
            for line in f:
                # normalize line endings (CRLF-friendly)
                raw = line.rstrip('\n')
                raw = raw[:-1] if raw.endswith('\r') else raw

                if state == 'idle':
                    if not raw.strip():
                        continue
                    RU = raw.upper()
                    if raw.startswith('--') or RU.startswith('SET ') or RU.startswith('SELECT PG_CATALOG'):
                        continue
                    if RU.startswith('CREATE EXTENSION') or RU.startswith('COMMENT ON '):
                        continue
                    if RU.startswith('ALTER SEQUENCE') or RU.startswith('CREATE SEQUENCE'):
                        continue
                    if RU.startswith('ALTER TABLE') and 'OWNER TO' in RU:
                        continue
                    if RU.startswith('ALTER TABLE ONLY') and ('SET DEFAULT NEXTVAL' in RU or 'ADD CONSTRAINT' in RU):
                        continue

                    if RU.startswith('CREATE TABLE '):
                        create_block_lines = [raw]
                        state = 'in_create'
                        continue

                    if RU.startswith('COPY '):
                        table, cols = parse_copy_header(raw)
                        if table is not None:
                            copy_table, copy_cols = table, cols
                            if copy_cols is None:
                                # fetch actual column order from table info
                                info = cur.execute(f'PRAGMA table_info("{copy_table}")').fetchall()
                                copy_cols = [r[1] for r in info]
                            casters = build_type_casts(cur, copy_table, copy_cols)
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
                        copy_table, copy_cols, casters = None, None, None
                        state = 'idle'
                        continue

                    parts = raw.split('\t')
                    # fast path, then fallback through csv for very odd cases
                    if copy_cols and len(parts) != len(copy_cols):
                        reader = csv.reader([raw], delimiter='\t', quoting=csv.QUOTE_MINIMAL)
                        parts = next(reader)
                    if copy_cols and len(parts) != len(copy_cols):
                        raise RuntimeError(f"COPY row has {len(parts)} fields but expected {len(copy_cols)} for table {copy_table}. Problematic line:\n{raw}")

                    row = [decode_pg_field(p) for p in parts]
                    # cast types
                    if casters:
                        row = [fn(v) for fn, v in zip(casters, row)]

                    copy_rows_buffer.append(row)
                    if len(copy_rows_buffer) >= 2000:
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

    # ------------- Schema report -------------
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
            md_lines.append(f"| {cid} | `{name}` | `{coltype}` | {('✅' if notnull else '')} | {str(dflt_value) if dflt_value is not None else 'NULL'} | {('✅' if pk else '')} |")

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
                    md_lines.append("| " + " | ".join('NULL' if v is None else str(v).replace('\n',' ').replace('\r',' ') for v in r) + " |")
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
