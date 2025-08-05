import argparse
import json
import sqlite3
from typing import List, Dict, Any, Tuple

from keys import DB_NAME


def create_tables(conn: sqlite3.Connection, schema_file: str = 'table_shem.json') -> None:
    """Ensure all tables from schema exist in the SQLite database."""
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    cur = conn.cursor()
    for stmt in schema.values():
        cur.execute(f'CREATE TABLE IF NOT EXISTS {stmt}')
    conn.commit()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_copy_section(dump_path: str, table: str) -> List[List[Any]]:
    """Return raw rows from COPY section for given table name."""
    rows: List[List[Any]] = []
    in_section = False

    with open(dump_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.rstrip('\n')

            if not in_section:
                if line.startswith(f'COPY public.{table} '):
                    in_section = True
                continue

            if line == '\\.':
                break

            rows.append([None if p == '\\N' else p for p in line.split('\t')])

    return rows


def parse_clients(dump_path: str) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """Extract clients and build a mapping by original id."""
    rows = _parse_copy_section(dump_path, 'clients')
    clients: List[Dict[str, Any]] = []
    by_id: Dict[int, Dict[str, Any]] = {}

    for parts in rows:
        client = {
            'id': int(parts[0]),
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
        }
        clients.append(client)
        by_id[client['id']] = client

    return clients, by_id


def parse_chats(dump_path: str) -> Dict[int, Dict[str, Any]]:
    rows = _parse_copy_section(dump_path, 'chats')
    chats: Dict[int, Dict[str, Any]] = {}
    for parts in rows:
        chats[int(parts[0])] = {
            'client_id': int(parts[1]),
            'telegram_id': parts[2],
        }
    return chats


def parse_chat_messages(dump_path: str) -> List[Dict[str, Any]]:
    rows = _parse_copy_section(dump_path, 'chat_messages')
    messages: List[Dict[str, Any]] = []
    for parts in rows:
        messages.append({
            'chat_id': int(parts[1]),
            'telegram_id': int(parts[2]) if parts[2] else None,
            'from_client': str(parts[3]).lower() in {'t', 'true', '1'},
            'text': parts[4],
            'files': json.loads(parts[5]) if parts[5] else None,
            'telegram_data': json.loads(parts[6]) if parts[6] else None,
            'created_at': parts[7],
        })
    return messages


def parse_support_requests(dump_path: str) -> List[Dict[str, Any]]:
    rows = _parse_copy_section(dump_path, 'support_requests')
    requests: List[Dict[str, Any]] = []
    for parts in rows:
        requests.append({
            'id': int(parts[0]),
            'client_id': int(parts[1]),
            'message': parts[2],
            'created_at': parts[3],
        })
    return requests


def parse_newsletters(dump_path: str) -> List[Dict[str, Any]]:
    rows = _parse_copy_section(dump_path, 'newsletters')
    letters: List[Dict[str, Any]] = []
    for parts in rows:
        letters.append({
            'id': int(parts[0]),
            'status': parts[1],
            'time': parts[2],
            'content': parts[3],
            'created_at': parts[4],
            'image': parts[7],
        })
    return letters


def parse_game_ratings(dump_path: str) -> List[Dict[str, Any]]:
    rows = _parse_copy_section(dump_path, 'game_ratings')
    ratings: List[Dict[str, Any]] = []
    for parts in rows:
        ratings.append({
            'client_id': int(parts[1]),
            'rating': int(parts[2]),
            'created_at': parts[3],
        })
    return ratings


# ---------------------------------------------------------------------------
# Migration routines
# ---------------------------------------------------------------------------

def migrate_clients(clients: List[Dict[str, Any]], conn: sqlite3.Connection) -> None:
    """Insert parsed client rows into our local schema."""
    cur = conn.cursor()

    for c in clients:
        full_name = ' '.join(
            filter(None, [c['name'], c['surname'], c['patronymic']])
        ).strip() or None
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


def migrate_chat_messages(
    messages: List[Dict[str, Any]],
    chats: Dict[int, Dict[str, Any]],
    clients_by_id: Dict[int, Dict[str, Any]],
    conn: sqlite3.Connection,
) -> None:
    """Insert chat messages into participant_messages table."""
    cur = conn.cursor()
    cur.execute('PRAGMA table_info(participant_messages)')
    cols = [r[1] for r in cur.fetchall()]
    has_is_answer = 'is_answer' in cols
    has_is_deleted = 'is_deleted' in cols

    for m in messages:
        chat = chats.get(m['chat_id'])
        if not chat:
            continue
        client = clients_by_id.get(chat['client_id'])
        if not client:
            continue

        user_tg_id = client['telegram_id']
        sender = 'user' if m['from_client'] else 'admin'

        media_payload: Dict[str, Any] = {}
        if m.get('telegram_id') is not None:
            media_payload['telegram_id'] = m['telegram_id']
        if m['files'] is not None:
            media_payload['files'] = m['files']
        if m['telegram_data'] is not None:
            media_payload['telegram_data'] = m['telegram_data']
        media_json = json.dumps(media_payload, ensure_ascii=False) if media_payload else None

        columns = ['user_tg_id', 'sender', 'text', 'buttons', 'media', 'timestamp']
        values = [user_tg_id, sender, m['text'], None, media_json, m['created_at']]

        if has_is_answer:
            columns.append('is_answer')
            values.append(0 if m['from_client'] else 1)
        if has_is_deleted:
            columns.append('is_deleted')
            values.append(0)

        placeholders = ','.join(['?'] * len(values))
        cur.execute(
            f"INSERT OR IGNORE INTO participant_messages ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )

    conn.commit()


def migrate_support_requests(
    requests: List[Dict[str, Any]],
    clients_by_id: Dict[int, Dict[str, Any]],
    conn: sqlite3.Connection,
) -> None:
    """Insert support requests into questions and question_messages tables."""
    cur = conn.cursor()

    for r in requests:
        client = clients_by_id.get(r['client_id'])
        if not client:
            continue
        user_tg_id = client['telegram_id']

        cur.execute(
            'INSERT OR IGNORE INTO questions (id, user_tg_id, text, type, status, create_dt)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (r['id'], user_tg_id, r['message'], 'support', 'imported', r['created_at']),
        )

        cur.execute(
            'INSERT OR IGNORE INTO question_messages (id, question_id, sender, text, is_answer, timestamp)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (r['id'], r['id'], 'user', r['message'], 0, r['created_at']),
        )

    conn.commit()


def migrate_newsletters(letters: List[Dict[str, Any]], conn: sqlite3.Connection) -> None:
    """Insert newsletters into scheduled_messages table."""
    cur = conn.cursor()
    for n in letters:
        schedule_dt = n['time'] or n['created_at']
        cur.execute(
            'INSERT OR IGNORE INTO scheduled_messages (name, content, schedule_dt, status, media, create_dt) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (f'newsletter_{n["id"]}', n['content'], schedule_dt, n['status'], n['image'], n['created_at']),
        )
    conn.commit()


def migrate_game_ratings(
    ratings: List[Dict[str, Any]],
    clients_by_id: Dict[int, Dict[str, Any]],
    conn: sqlite3.Connection,
) -> None:
    """Convert game ratings into a prize draw with participants."""
    if not ratings:
        return

    cur = conn.cursor()
    start = min(r['created_at'] for r in ratings if r['created_at'])
    end = max(r['created_at'] for r in ratings if r['created_at'])

    cur.execute(
        'INSERT INTO prize_draws (title, start_date, end_date, status, create_dt) VALUES (?, ?, ?, ?, ?)',
        ('Imported tournament', start, end, 'completed', start),
    )
    draw_id = cur.lastrowid
    cur.execute(
        'INSERT INTO prize_draw_stages (draw_id, name, description, winners_count, order_index, create_dt) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (draw_id, 'Ratings', 'Imported from finsky.sql', 0, 0, start),
    )
    stage_id = cur.lastrowid

    for r in ratings:
        client = clients_by_id.get(r['client_id'])
        if not client:
            continue
        full_name = ' '.join(filter(None, [client['name'], client['surname'], client['patronymic']])) or 'unknown'
        cur.execute(
            'INSERT OR IGNORE INTO prize_draw_winners (stage_id, user_tg_id, receipt_id, winner_name, create_dt) '
            'VALUES (?, ?, ?, ?, ?)',
            (stage_id, client['telegram_id'], r['rating'], full_name, r['created_at']),
        )

    conn.commit()


def main(dump_path: str, db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    create_tables(conn)

    clients, clients_by_id = parse_clients(dump_path)
    migrate_clients(clients, conn)

    chats = parse_chats(dump_path)
    messages = parse_chat_messages(dump_path)
    migrate_chat_messages(messages, chats, clients_by_id, conn)

    support_requests = parse_support_requests(dump_path)
    migrate_support_requests(support_requests, clients_by_id, conn)

    newsletters = parse_newsletters(dump_path)
    migrate_newsletters(newsletters, conn)

    ratings = parse_game_ratings(dump_path)
    migrate_game_ratings(ratings, clients_by_id, conn)

    conn.close()
    print(
        f'Migrated {len(clients)} clients, '
        f'{len(messages)} chat messages, '
        f'{len(support_requests)} support requests, '
        f'{len(newsletters)} newsletters and '
        f'{len(ratings)} game ratings into {db_path}'
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Migrate data from finsky dump to local database.'
    )
    parser.add_argument('--dump', default='finsky.sql', help='Path to finsky.sql dump')
    parser.add_argument('--db', default=DB_NAME, help='Path to target SQLite database')
    args = parser.parse_args()
    main(args.dump, args.db)

