"""
Migrate data from legacy Finsky PostgreSQL database into our PostgreSQL database.

Usage:
    python migrate_finsky.py --source postgresql://user:pass@localhost/finsky \
                             --target postgresql://user:pass@localhost/ourdb
"""

import argparse
import json
from typing import Any, Dict, List

import sqlalchemy as sa
from sqlalchemy.orm import Session, declarative_base


Base = declarative_base()


class Clients(Base):
    __tablename__ = 'clients'
    id = sa.Column(sa.Integer, primary_key=True)
    telegram_id = sa.Column(sa.Integer, nullable=False)
    created_at = sa.Column(sa.DateTime)
    updated_at = sa.Column(sa.DateTime)
    deleted_at = sa.Column(sa.DateTime)
    phone = sa.Column(sa.Text)
    last_action_at = sa.Column(sa.DateTime)
    name = sa.Column(sa.Text)
    surname = sa.Column(sa.Text)
    patronymic = sa.Column(sa.Text)
    started_at = sa.Column(sa.DateTime)
    comment = sa.Column(sa.Text)
    status = sa.Column(sa.Text)
    menu_state = sa.Column(sa.Integer, nullable=False, server_default=sa.text("0"))
    is_tester = sa.Column(sa.Boolean, nullable=False, server_default=sa.text("0"))


class Chats(Base):
    __tablename__ = 'chats'
    id = sa.Column(sa.Integer, primary_key=True)
    client_id = sa.Column(sa.Integer, nullable=False)
    telegram_id = sa.Column(sa.Text, nullable=False)
    created_at = sa.Column(sa.DateTime)
    updated_at = sa.Column(sa.DateTime)
    log_enable = sa.Column(sa.Boolean, nullable=False, server_default=sa.text("1"))


class ChatMessages(Base):
    __tablename__ = 'chat_messages'
    id = sa.Column(sa.Integer, primary_key=True)
    chat_id = sa.Column(sa.Integer, nullable=False)
    telegram_id = sa.Column(sa.Text)
    from_client = sa.Column(sa.Boolean, nullable=False, server_default=sa.text("1"))
    text = sa.Column(sa.Text)
    files = sa.Column(sa.Text)
    telegram_data = sa.Column(sa.Text)
    created_at = sa.Column(sa.DateTime)
    updated_at = sa.Column(sa.DateTime)


class SupportRequests(Base):
    __tablename__ = 'support_requests'
    id = sa.Column(sa.Integer, primary_key=True)
    client_id = sa.Column(sa.Integer, nullable=False)
    message = sa.Column(sa.Text, nullable=False)
    created_at = sa.Column(sa.DateTime)
    updated_at = sa.Column(sa.DateTime)
    deleted_at = sa.Column(sa.DateTime)


class Newsletters(Base):
    __tablename__ = 'newsletters'
    id = sa.Column(sa.Integer, primary_key=True)
    status = sa.Column(sa.Integer, nullable=False)
    time = sa.Column(sa.DateTime)
    content = sa.Column(sa.Text, nullable=False)
    created_at = sa.Column(sa.DateTime)
    updated_at = sa.Column(sa.DateTime)
    deleted_at = sa.Column(sa.DateTime)
    image = sa.Column(sa.Text)
    attach_button = sa.Column(sa.Boolean)


class GameRatings(Base):
    __tablename__ = 'game_ratings'
    id = sa.Column(sa.Integer, primary_key=True)
    client_id = sa.Column(sa.Integer, nullable=False)
    rating = sa.Column(sa.Float, nullable=False)
    created_at = sa.Column(sa.DateTime)
    updated_at = sa.Column(sa.DateTime)
    deleted_at = sa.Column(sa.DateTime)


# ---------------------------------------------------------------------------
# Migration routines
# ---------------------------------------------------------------------------

def migrate_clients(clients: List[Clients], conn: sa.Connection) -> Dict[int, Clients]:
    """Insert clients into target DB and build mapping by id."""
    by_id: Dict[int, Clients] = {}
    for c in clients:
        by_id[c.id] = c
        full_name = ' '.join(filter(None, [c.name, c.surname, c.patronymic])) or None
        conn.execute(
            sa.text(
                "INSERT INTO users (tg_id, name, phone, create_dt) "
                "VALUES (:tg_id, :name, :phone, :created_at) "
                "ON CONFLICT (tg_id) DO NOTHING"
            ),
            {
                'tg_id': c.telegram_id,
                'name': full_name,
                'phone': c.phone,
                'created_at': c.created_at,
            },
        )

        extra = {
            'surname': c.surname,
            'patronymic': c.patronymic,
            'comment': c.comment,
            'status': c.status,
            'menu_state': c.menu_state,
            'is_tester': c.is_tester,
            'last_action_at': c.last_action_at,
            'started_at': c.started_at,
        }
        extra = {k: v for k, v in extra.items() if v is not None}
        if extra:
            conn.execute(
                sa.text(
                    "INSERT INTO user_extended (tg_id, all_data) "
                    "VALUES (:tg_id, :data) ON CONFLICT (tg_id) DO NOTHING"
                ),
                {
                    'tg_id': c.telegram_id,
                    'data': json.dumps(extra, ensure_ascii=False),
                },
            )
    return by_id


def migrate_chat_messages(
    messages: List[ChatMessages],
    chats: Dict[int, Chats],
    clients_by_id: Dict[int, Clients],
    conn: sa.Connection,
) -> None:
    cols = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='participant_messages'"
            )
        )
    }
    has_is_answer = 'is_answer' in cols
    has_is_deleted = 'is_deleted' in cols

    for m in messages:
        chat = chats.get(m.chat_id)
        if not chat:
            continue
        client = clients_by_id.get(chat.client_id)
        if not client:
            continue
        user_tg_id = client.telegram_id
        sender = 'user' if m.from_client else 'admin'

        media_payload: Dict[str, Any] = {}
        if m.telegram_id:
            media_payload['telegram_id'] = m.telegram_id
        if m.files:
            try:
                media_payload['files'] = json.loads(m.files)
            except Exception:
                media_payload['files'] = m.files
        if m.telegram_data:
            try:
                media_payload['telegram_data'] = json.loads(m.telegram_data)
            except Exception:
                media_payload['telegram_data'] = m.telegram_data
        media_json = json.dumps(media_payload, ensure_ascii=False) if media_payload else None

        columns = ['user_tg_id', 'sender', 'text', 'buttons', 'media', 'timestamp']
        values = {
            'user_tg_id': user_tg_id,
            'sender': sender,
            'text': m.text,
            'buttons': None,
            'media': media_json,
            'timestamp': m.created_at,
        }
        if has_is_answer:
            columns.append('is_answer')
            values['is_answer'] = 0 if m.from_client else 1
        if has_is_deleted:
            columns.append('is_deleted')
            values['is_deleted'] = False

        col_sql = ', '.join(columns)
        placeholders = ', '.join(f":{c}" for c in columns)
        conn.execute(sa.text(f"INSERT INTO participant_messages ({col_sql}) VALUES ({placeholders})"), values)


def migrate_support_requests(
    requests: List[SupportRequests],
    clients_by_id: Dict[int, Clients],
    conn: sa.Connection,
) -> None:
    for r in requests:
        client = clients_by_id.get(r.client_id)
        if not client:
            continue
        user_tg_id = client.telegram_id
        conn.execute(
            sa.text(
                "INSERT INTO questions (id, user_tg_id, text, type, status, create_dt) "
                "VALUES (:id, :tg_id, :text, 'support', 'imported', :created_at) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {'id': r.id, 'tg_id': user_tg_id, 'text': r.message, 'created_at': r.created_at},
        )
        conn.execute(
            sa.text(
                "INSERT INTO question_messages (id, question_id, sender, text, is_answer, timestamp) "
                "VALUES (:id, :qid, 'user', :text, 0, :created_at) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {'id': r.id, 'qid': r.id, 'text': r.message, 'created_at': r.created_at},
        )


def migrate_newsletters(letters: List[Newsletters], conn: sa.Connection) -> None:
    for n in letters:
        schedule_dt = n.time or n.created_at
        conn.execute(
            sa.text(
                "INSERT INTO scheduled_messages (name, content, schedule_dt, status, media, create_dt) "
                "VALUES (:name, :content, :schedule_dt, :status, :media, :created_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                'name': f'newsletter_{n.id}',
                'content': n.content,
                'schedule_dt': schedule_dt,
                'status': n.status,
                'media': n.image,
                'created_at': n.created_at,
            },
        )


def migrate_game_ratings(
    ratings: List[GameRatings],
    clients_by_id: Dict[int, Clients],
    conn: sa.Connection,
) -> None:
    if not ratings:
        return
    start = min(r.created_at for r in ratings if r.created_at)
    end = max(r.created_at for r in ratings if r.created_at)
    draw_id = conn.execute(
        sa.text(
            "INSERT INTO prize_draws (title, start_date, end_date, status, create_dt) "
            "VALUES (:title, :start, :end, 'completed', :start) RETURNING id"
        ),
        {'title': 'Imported tournament', 'start': start, 'end': end},
    ).scalar_one()
    stage_id = conn.execute(
        sa.text(
            "INSERT INTO prize_draw_stages (draw_id, name, description, winners_count, order_index, create_dt) "
            "VALUES (:draw_id, 'Ratings', 'Imported from finsky.sql', 0, 0, :start) RETURNING id"
        ),
        {'draw_id': draw_id, 'start': start},
    ).scalar_one()

    for r in ratings:
        client = clients_by_id.get(r.client_id)
        if not client:
            continue
        full_name = ' '.join(
            filter(None, [client.name, client.surname, client.patronymic])
        ) or 'unknown'
        conn.execute(
            sa.text(
                "INSERT INTO prize_draw_winners (stage_id, user_tg_id, receipt_id, winner_name, create_dt) "
                "VALUES (:stage_id, :tg_id, :receipt_id, :winner_name, :created_at) ON CONFLICT DO NOTHING"
            ),
            {
                'stage_id': stage_id,
                'tg_id': client.telegram_id,
                'receipt_id': r.rating,
                'winner_name': full_name,
                'created_at': r.created_at,
            },
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def migrate(source_url: str, target_url: str) -> None:
    src_engine = sa.create_engine(source_url)
    dst_engine = sa.create_engine(target_url)

    with Session(src_engine) as session, dst_engine.begin() as conn:
        clients = session.query(Clients).all()
        clients_by_id = migrate_clients(clients, conn)

        chats = {c.id: c for c in session.query(Chats).all()}
        messages = session.query(ChatMessages).all()
        migrate_chat_messages(messages, chats, clients_by_id, conn)

        support_requests = session.query(SupportRequests).all()
        migrate_support_requests(support_requests, clients_by_id, conn)

        letters = session.query(Newsletters).all()
        migrate_newsletters(letters, conn)

        ratings = session.query(GameRatings).all()
        migrate_game_ratings(ratings, clients_by_id, conn)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Migrate data from Finsky PostgreSQL database.'
    )
    parser.add_argument('--source', required=True, help='SQLAlchemy DSN of source database')
    parser.add_argument('--target', required=True, help='SQLAlchemy DSN of target database')
    args = parser.parse_args()
    migrate(args.source, args.target)


if __name__ == '__main__':
    main()

