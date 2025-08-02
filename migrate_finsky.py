import argparse
import json
import sqlite3
from typing import List, Dict, Any

from keys import DB_NAME


def create_tables(conn: sqlite3.Connection, schema_file: str = 'table_shem.json') -> None:
    """Ensure all tables from schema exist in the SQLite database."""
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    cur = conn.cursor()
    for stmt in schema.values():
        cur.execute(f'CREATE TABLE IF NOT EXISTS {stmt}')
    conn.commit()


def parse_clients(dump_path: str) -> List[Dict[str, Any]]:
    """Extract rows of the `clients` table from a Postgres dump produced by pg_dump."""
    clients = []
    in_section = False

    with open(dump_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.rstrip('\n')

            if not in_section:
                if line.startswith('COPY public.clients'):
                    in_section = True
                continue

            if line == '\\.':
                break

            parts = [None if p == '\\N' else p for p in line.split('\t')]
            clients.append({
                'telegram_id': parts[1],
                'created_at': parts[2],
                'phone': parts[5],
                'last_action_at': parts[6],
                'name': parts[7],
                'surname': parts[8],
                'patronymic': parts[9],
                'started_at': parts[10],
                'comment': parts[11],
                'status': parts[12],
                'menu_state': parts[13],
                'is_tester': parts[14],
            })

    return clients


def migrate_clients(clients: List[Dict[str, Any]], conn: sqlite3.Connection) -> None:
    """Insert parsed client rows into our local schema."""
    cur = conn.cursor()

    for c in clients:
        full_name = ' '.join(filter(None, [c['name'], c['surname'], c['patronymic']])).strip() or None
        cur.execute(
            'INSERT OR IGNORE INTO users (tg_id, name, phone, create_dt) VALUES (?, ?, ?, ?)',
            (c['telegram_id'], full_name, c['phone'], c['created_at']),
        )

        extra = {
            'surname': c['surname'],
            'patronymic': c['patronymic'],
            'comment': c['comment'],
            'status': c['status'],
            'menu_state': c['menu_state'],
            'is_tester': c['is_tester'],
            'last_action_at': c['last_action_at'],
            'started_at': c['started_at'],
        }
        extra = {k: v for k, v in extra.items() if v is not None}
        if extra:
            cur.execute(
                'INSERT OR REPLACE INTO user_extended (tg_id, all_data) VALUES (?, ?)',
                (c['telegram_id'], json.dumps(extra, ensure_ascii=False)),
            )

    conn.commit()


def main(dump_path: str, db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    clients = parse_clients(dump_path)
    migrate_clients(clients, conn)
    conn.close()
    print(f'Migrated {len(clients)} clients into {db_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Migrate clients from finsky dump to local database.')
    parser.add_argument('--dump', default='finsky.sql', help='Path to finsky.sql dump')
    parser.add_argument('--db', default=DB_NAME, help='Path to target SQLite database')
    args = parser.parse_args()
    main(args.dump, args.db)
