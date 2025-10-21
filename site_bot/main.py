# main.py

from fastapi import FastAPI, Request, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-store"
        return response
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from databases import Database
import sqlalchemy
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from typing import List, Optional, Dict, Any, Tuple, Set
import datetime
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import logging

# Админ-панель через SQLAdmin
from sqladmin import Admin, ModelView
import asyncio
import contextlib
import json
import os
import uuid
from pathlib import Path
import random
import csv
import io
from decimal import Decimal
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sql_mgt import (
    ensure_receipt_comment_column_sync,
    get_table_schema_columns,
    get_table_schema_sql,
)

# aiogram is imported lazily when sending messages

# ==============================
# Настройка БД
# ==============================
def _resolve_database_file(default_path: str) -> Path:
    raw_path = Path(default_path)
    if raw_path.is_absolute():
        return raw_path
    base_dir = Path(__file__).resolve().parent
    search_roots = [base_dir, *base_dir.parents]
    for root in search_roots:
        candidate = (root / raw_path).resolve()
        if candidate.exists():
            return candidate
    return (base_dir / raw_path).resolve()


DATABASE_FILE = _resolve_database_file("../../tg_base.sqlite")
DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()
logger = logging.getLogger(__name__)

UTC = datetime.timezone.utc
MSK_TZ = datetime.timezone(datetime.timedelta(hours=3), name="MSK")

SCHEDULE_POLL_SECONDS = int(os.getenv("SCHEDULE_POLL_SECONDS", "60"))
SCHEDULE_RETRY_MINUTES = int(os.getenv("SCHEDULE_RETRY_MINUTES", "5"))
SCHEDULE_RETRY_INTERVAL = datetime.timedelta(minutes=SCHEDULE_RETRY_MINUTES)
SCHEDULE_ALLOWED_STATUSES = {
    "Черновик",
    "Запланирована",
    "Идёт отправка",
    "Отправлено",
    "Ошибка",
}
SCHEDULE_MAX_ERROR_LENGTH = 800
_schedule_lock = asyncio.Lock()

_SCHEDULED_MESSAGES_SCHEMA_SQL = get_table_schema_sql("scheduled_messages")
_SCHEDULED_MESSAGES_COLUMNS = get_table_schema_columns("scheduled_messages")

if _SCHEDULED_MESSAGES_COLUMNS:
    SCHEDULED_MESSAGES_EXPECTED_COLUMNS: Tuple[Tuple[str, str], ...] = tuple(
        _SCHEDULED_MESSAGES_COLUMNS
    )
else:
    SCHEDULED_MESSAGES_EXPECTED_COLUMNS = (
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("name", "TEXT NOT NULL"),
        ("content", "TEXT NOT NULL"),
        ("schedule_dt", "TIMESTAMP"),
        ("status", "TEXT NOT NULL DEFAULT 'Черновик'"),
        ("auto_send", "INTEGER DEFAULT 0"),
        ("media", "TEXT"),
        ("last_attempt_dt", "TIMESTAMP"),
        ("sent_dt", "TIMESTAMP"),
        ("last_error", "TEXT"),
        ("success_count", "INTEGER DEFAULT 0"),
        ("failure_count", "INTEGER DEFAULT 0"),
        ("created_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP"),
    )

SCHEDULED_MESSAGES_CREATE_STATEMENT = (
    _SCHEDULED_MESSAGES_SCHEMA_SQL
    or "scheduled_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, content TEXT NOT NULL, schedule_dt TIMESTAMP, status TEXT NOT NULL DEFAULT 'Черновик', auto_send INTEGER DEFAULT 0, media TEXT, last_attempt_dt TIMESTAMP, sent_dt TIMESTAMP, last_error TEXT, success_count INTEGER DEFAULT 0, failure_count INTEGER DEFAULT 0, created_at TIMESTAMP, updated_at TIMESTAMP)"
)

SCHEDULED_MESSAGES_COPY_DEFAULTS: Dict[str, str] = {
    "status": "'Черновик'",
    "auto_send": "0",
    "media": "NULL",
    "last_attempt_dt": "NULL",
    "sent_dt": "NULL",
    "last_error": "NULL",
    "success_count": "0",
    "failure_count": "0",
    "created_at": "CURRENT_TIMESTAMP",
    "updated_at": "CURRENT_TIMESTAMP",
}


def _ensure_receipts_schema() -> None:
    """Ensure the receipts table has the expected primary key and comment column."""
    try:
        db_path = make_url(DATABASE_URL).database or ""
        db_file = Path(db_path)
        if not db_file.is_absolute():
            db_file = (Path(__file__).resolve().parent / db_file).resolve()
        ensure_receipt_comment_column_sync(str(db_file))
    except Exception:
        logger.exception("Failed to ensure receipts schema")


_ensure_receipts_schema()


def _ensure_scheduled_messages_schema() -> None:
    """Ensure the scheduled_messages table exists with the expected columns."""

    if not SCHEDULED_MESSAGES_EXPECTED_COLUMNS:
        logger.warning(
            "No scheduled_messages schema definition was found; skipping auto migration"
        )
        return

    column_def_sql = ",\n                ".join(
        f"{name} {ddl}" for name, ddl in SCHEDULED_MESSAGES_EXPECTED_COLUMNS
    )

    def rebuild_table(connection: "sqlalchemy.engine.Connection") -> Dict[str, Any]:
        temp_table = "scheduled_messages_tmp"
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {temp_table}")
        connection.exec_driver_sql(
            f"""
            CREATE TABLE {temp_table} (
                {column_def_sql}
            )
            """
        )
        existing_columns = {
            row[1]: True
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(scheduled_messages)"
            )
        }
        insert_columns = [name for name, _ in SCHEDULED_MESSAGES_EXPECTED_COLUMNS]
        select_parts = []
        for name in insert_columns:
            if name in existing_columns:
                select_parts.append(name)
            else:
                select_parts.append(SCHEDULED_MESSAGES_COPY_DEFAULTS.get(name, "NULL"))
        connection.exec_driver_sql(
            f"INSERT INTO {temp_table} ({', '.join(insert_columns)}) "
            f"SELECT {', '.join(select_parts)} FROM scheduled_messages"
        )
        connection.exec_driver_sql("DROP TABLE scheduled_messages")
        connection.exec_driver_sql(
            f"ALTER TABLE {temp_table} RENAME TO scheduled_messages"
        )
        return {name: True for name, _ in SCHEDULED_MESSAGES_EXPECTED_COLUMNS}

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE IF NOT EXISTS {SCHEDULED_MESSAGES_CREATE_STATEMENT}"
            )
            existing_columns = {
                row[1]: True
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(scheduled_messages)"
                )
            }
            for name, ddl in SCHEDULED_MESSAGES_EXPECTED_COLUMNS:
                if name in existing_columns:
                    continue
                try:
                    connection.exec_driver_sql(
                        f"ALTER TABLE scheduled_messages ADD COLUMN {name} {ddl}"
                    )
                    existing_columns[name] = True
                except OperationalError:
                    logger.warning(
                        "Rebuilding scheduled_messages table to add missing column %s",
                        name,
                    )
                    existing_columns = rebuild_table(connection)
                    break
            if "created_at" in existing_columns:
                connection.exec_driver_sql(
                    "UPDATE scheduled_messages SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )
            if "updated_at" in existing_columns:
                connection.exec_driver_sql(
                    "UPDATE scheduled_messages SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
                )
    except Exception:
        logger.exception("Failed to ensure scheduled_messages schema")


_ensure_scheduled_messages_schema()

# Рефлексия всех таблиц
metadata.reflect(bind=engine)

# Core-Table объекты (для ваших маршрутов)
users_table                = Table("users", metadata, autoload_with=engine)
user_settings_table        = Table("user_settings", metadata, autoload_with=engine)
user_extended_table        = Table("user_extended", metadata, autoload_with=engine)
user_params_table          = Table("user_params", metadata, autoload_with=engine)
user_rule_table            = Table("user_rule", metadata, autoload_with=engine)
history_user_table         = Table("history_user", metadata, autoload_with=engine)
last_image_table           = Table("last_image", metadata, autoload_with=engine)
visite_log_table           = Table("visite_log", metadata, autoload_with=engine)
params_table               = Table("params", metadata, autoload_with=engine)
admins_table               = Table("admins", metadata, autoload_with=engine)
admin_invite_table         = Table("admin_invite", metadata, autoload_with=engine)
wallet_log_table           = Table("wallet_log", metadata, autoload_with=engine)
cancel_order_table         = Table("cancel_order", metadata, autoload_with=engine)
params_site_table          = Table("params_site", metadata, autoload_with=engine)
item_table                 = Table("item", metadata, autoload_with=engine)
sales_header_table         = Table("sales_header", metadata, autoload_with=engine)
sales_line_table           = Table("sales_line", metadata, autoload_with=engine)
additional_field_table     = Table("additional_field", metadata, autoload_with=engine)
questions_table            = Table("questions", metadata, autoload_with=engine)
question_messages_table    = Table("question_messages", metadata, autoload_with=engine)
scheduled_messages_table   = Table(
    "scheduled_messages", metadata, autoload_with=engine, extend_existing=True
)
prize_draws_table          = Table("prize_draws", metadata, autoload_with=engine)
prize_draw_stages_table    = Table("prize_draw_stages", metadata, autoload_with=engine)
prize_draw_winners_table   = Table("prize_draw_winners", metadata, autoload_with=engine)
participant_settings_table = Table("participant_settings", metadata, autoload_with=engine)
participant_messages_table = Table("participant_messages", metadata, autoload_with=engine)

# Some deployments may still use an older database schema without the
# `is_answer` column.  Detect its presence so we can behave gracefully
# when reading or writing data.
def _get_table_column_names(table_name: str) -> Set[str]:
    try:
        with engine.connect() as connection:
            return {
                row[1]
                for row in connection.exec_driver_sql(
                    f"PRAGMA table_info({table_name})"
                )
            }
    except Exception:
        logger.exception("Failed to inspect %s columns", table_name)
        return set()


SCHEDULED_MESSAGES_COLUMN_NAMES: Set[str] = set()
HAS_SM_AUTO_SEND = False
HAS_SM_MEDIA = False


def _set_scheduled_messages_column_flags(column_names: Set[str]) -> None:
    global SCHEDULED_MESSAGES_COLUMN_NAMES, HAS_SM_AUTO_SEND, HAS_SM_MEDIA
    SCHEDULED_MESSAGES_COLUMN_NAMES = set(column_names)
    HAS_SM_AUTO_SEND = "auto_send" in SCHEDULED_MESSAGES_COLUMN_NAMES
    HAS_SM_MEDIA = "media" in SCHEDULED_MESSAGES_COLUMN_NAMES


_set_scheduled_messages_column_flags(_get_table_column_names("scheduled_messages"))

HAS_PM_IS_ANSWER = 'is_answer' in participant_messages_table.c
HAS_QM_IS_ANSWER = 'is_answer' in question_messages_table.c


def _scheduled_messages_columns() -> List[Any]:
    columns: List[Any] = [
        scheduled_messages_table.c.id,
        scheduled_messages_table.c.name,
        scheduled_messages_table.c.content,
        scheduled_messages_table.c.schedule_dt,
        scheduled_messages_table.c.status,
    ]
    optional_map = {
        "auto_send": getattr(scheduled_messages_table.c, "auto_send", None),
        "media": getattr(scheduled_messages_table.c, "media", None),
        "last_attempt_dt": getattr(scheduled_messages_table.c, "last_attempt_dt", None),
        "sent_dt": getattr(scheduled_messages_table.c, "sent_dt", None),
        "last_error": getattr(scheduled_messages_table.c, "last_error", None),
        "success_count": getattr(scheduled_messages_table.c, "success_count", None),
        "failure_count": getattr(scheduled_messages_table.c, "failure_count", None),
        "created_at": getattr(scheduled_messages_table.c, "created_at", None),
        "updated_at": getattr(scheduled_messages_table.c, "updated_at", None),
    }
    for name, column in optional_map.items():
        if name in SCHEDULED_MESSAGES_COLUMN_NAMES and column is not None:
            columns.append(column)
    return columns


def _scheduled_messages_select() -> "sqlalchemy.sql.Select":
    return (
        sqlalchemy.select(*_scheduled_messages_columns())
        .select_from(scheduled_messages_table)
    )


async def _refresh_scheduled_messages_column_flags() -> None:
    try:
        rows = await database.fetch_all("PRAGMA table_info(scheduled_messages)")
    except Exception:
        logger.exception("Failed to refresh scheduled_messages column metadata")
        return
    column_names = {row["name"] for row in rows if "name" in row}
    if not column_names and rows:
        # Databases Record may expose tuple-style access
        column_names = {row[1] for row in rows}
    _set_scheduled_messages_column_flags(column_names)
HAS_PDW_RECEIPT_ID = 'receipt_id' in prize_draw_winners_table.c
receipts_table             = Table("receipts", metadata, autoload_with=engine)
images_table               = Table("images", metadata, autoload_with=engine)
deleted_images_table       = Table("deleted_images", metadata, autoload_with=engine)
notifications_table        = Table("notifications", metadata, autoload_with=engine)

def has_receipt_status() -> bool:
    """Return True if the receipts table has a 'status' column."""
    return 'status' in receipts_table.c

def has_receipt_msg_id() -> bool:
    """Return True if the receipts table has a 'message_id' column."""
    return 'message_id' in receipts_table.c

def has_receipt_draw_id() -> bool:
    """Return True if the receipts table has a 'draw_id' column."""
    return 'draw_id' in receipts_table.c


def has_receipt_comment() -> bool:
    """Return True if the receipts table has a 'comment' column."""
    return 'comment' in receipts_table.c

# Подготовка automap для ORM-классов
Base = automap_base(metadata=metadata)
Base.prepare()
SessionLocal = sessionmaker(bind=engine)

# ==============================
# FastAPI-приложение и middleware
# ==============================
app = FastAPI()
app.state.static_version = str(int(datetime.datetime.utcnow().timestamp()))
UPLOAD_DIR = Path(__file__).resolve().parent / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Сначала регистрируем AuthMiddleware, затем SessionMiddleware,
# чтобы сессия инициализировалась до проверки AuthMiddleware.
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/static") or request.url.path in ("/login", "/logout"):
            return await call_next(request)
        if not request.session.get("user"):
            return RedirectResponse(f"/login?next={request.url.path}", status_code=302)
        return await call_next(request)

app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key="YOUR_SECRET_KEY_HERE")

app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================
# Инициализация SQLAdmin
# ==============================
admin = Admin(app, engine, title="Админ-панель")

# Автоматическая регистрация всех моделей из automap
for name, model in Base.classes.items():    
    class AdminClass(ModelView, model=model):
        column_list = "__all__"
    admin.add_view(AdminClass)

# ==============================
# Стартап/шутдаун и ваши маршруты
# ==============================
@app.on_event("startup")
async def on_startup():
    await database.connect()
    await _refresh_scheduled_messages_column_flags()
    app.state.scheduler_task = asyncio.create_task(_scheduled_sender_loop())

@app.on_event("shutdown")
async def on_shutdown():
    task = getattr(app.state, "scheduler_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await database.disconnect()

# ==============================
# Маршруты авторизации
# ==============================
@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    next_url = request.query_params.get("next", "/")
    return templates.TemplateResponse(
        "login.html", {"request": request, "next": next_url, "version": app.state.static_version}
    )

@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/")
):
    # TODO: replace with real DB lookup
    if username == "admin" and password == "password":
        request.session["user"] = username
        return RedirectResponse(next, status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Неверные имя пользователя или пароль", "next": next, "version": app.state.static_version},
        status_code=401
    )

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

# ==============================
# Your existing application routes
# ==============================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(
        "prize_draws.html", {"request": request, "active_page": "prize_draws", "version": app.state.static_version}
    )

@app.get("/prize-draws", response_class=HTMLResponse)
async def prize_draws(request: Request):
    draw_query = sqlalchemy.select(
        prize_draws_table.c.id,
        prize_draws_table.c.title,
        sqlalchemy.cast(prize_draws_table.c.start_date, sqlalchemy.String).label("start_date"),
        sqlalchemy.cast(prize_draws_table.c.end_date, sqlalchemy.String).label("end_date"),
        prize_draws_table.c.status,
    )
    draws_rows = await database.fetch_all(draw_query)
    draws = []
    for d in draws_rows:
        stages = []
        stages_rows = await database.fetch_all(
            prize_draw_stages_table.select().where(
                prize_draw_stages_table.c.draw_id == d["id"]
            )
        )
        for idx, s in enumerate(stages_rows):
            if HAS_PDW_RECEIPT_ID:
                winners_rows = await database.fetch_all(
                    sqlalchemy.select(
                        prize_draw_winners_table.c.winner_name,
                        prize_draw_winners_table.c.user_tg_id,
                        prize_draw_winners_table.c.receipt_id,
                        receipts_table.c.file_path,
                        users_table.c.name.label("user_name"),
                    )
                    .select_from(
                        prize_draw_winners_table
                        .outerjoin(
                            receipts_table,
                            receipts_table.c.id
                            == prize_draw_winners_table.c.receipt_id,
                        )
                        .outerjoin(
                            users_table,
                            users_table.c.tg_id
                            == prize_draw_winners_table.c.user_tg_id,
                        )
                    )
                    .where(prize_draw_winners_table.c.stage_id == s["id"])
                )
            else:
                winners_rows = await database.fetch_all(
                    sqlalchemy.select(
                        prize_draw_winners_table.c.winner_name,
                        prize_draw_winners_table.c.user_tg_id,
                        receipts_table.c.file_path,
                        users_table.c.name.label("user_name"),
                    )
                    .select_from(
                        prize_draw_winners_table
                        .outerjoin(
                            receipts_table,
                            sqlalchemy.and_(
                                receipts_table.c.user_tg_id
                                == prize_draw_winners_table.c.user_tg_id,
                                receipts_table.c.draw_id == d["id"],
                            ),
                        )
                        .outerjoin(
                            users_table,
                            users_table.c.tg_id
                            == prize_draw_winners_table.c.user_tg_id,
                        )
                    )
                    .where(prize_draw_winners_table.c.stage_id == s["id"])
                )
            winners = []
            for w in winners_rows:
                file_path = w["file_path"]
                if file_path and not file_path.startswith("/static"):
                    file_path = f"/static/uploads/{Path(file_path).name}"
                winner_obj = {
                    "name": w["user_name"] or w["winner_name"],
                    "user_id": w["user_tg_id"],
                    "file": file_path,
                }
                if HAS_PDW_RECEIPT_ID and "receipt_id" in w:
                    winner_obj["receipt_id"] = w["receipt_id"]
                winners.append(winner_obj)
            stages.append(
                {
                    "__id": f"stage-{s['id']}",
                    "id": s["id"],
                    "name": s["name"],
                    "description": s["description"],
                    "winnersCount": s["winners_count"],
                    "textBefore": s["text_before"],
                    "textAfter": s["text_after"],
                    "winners": winners,
                }
            )
        start_dt = datetime.datetime.fromisoformat(d["start_date"]).date()
        end_dt = datetime.datetime.fromisoformat(d["end_date"]).date()
        draws.append({
            "id": d["id"],
            "title": d["title"],
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "status": d["status"],
            "stages": stages,
        })
    return templates.TemplateResponse(
        "prize_draws.html",
        {"request": request, "active_page": "prize_draws", "draws_data": draws, "version": app.state.static_version},
    )

class StageIn(BaseModel):
    __id: Optional[str]
    name: str
    description: Optional[str] = None
    winnersCount: int
    textBefore: Optional[str] = None
    textAfter: Optional[str] = None
    winners: List[Any] = []

class DrawIn(BaseModel):
    id: Optional[int] = None
    title: str
    start: datetime.date
    end: datetime.date
    status: str
    stages: List[StageIn]

@app.post("/prize-draws")
async def save_draw(draw: DrawIn):
    # validate date range
    if draw.end <= draw.start:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала")

    # ensure no overlap with other active draws
    if draw.status == "active":
        overlap_query = (
            sqlalchemy.select(prize_draws_table.c.id)
            .where(prize_draws_table.c.status == "active")
            .where(prize_draws_table.c.id != (draw.id if draw.id is not None else -1))
            .where(prize_draws_table.c.start_date <= draw.end)
            .where(prize_draws_table.c.end_date >= draw.start)
        )
        conflict = await database.fetch_one(overlap_query)
        if conflict:
            raise HTTPException(status_code=400, detail="Период пересекается с другим активным розыгрышем")

    if draw.id is None:
        new_id = await database.execute(
            prize_draws_table.insert().values(
                title=draw.title,
                start_date=draw.start,
                end_date=draw.end,
                status=draw.status
            )
        )
    else:
        new_id = draw.id
        await database.execute(
            prize_draws_table.update()
            .where(prize_draws_table.c.id == new_id)
            .values(
                title=draw.title,
                start_date=draw.start,
                end_date=draw.end,
                status=draw.status
            )
        )

    # delete old stages and winners
    old_stage_ids = await database.fetch_all(
        sqlalchemy.select(prize_draw_stages_table.c.id)
        .where(prize_draw_stages_table.c.draw_id == new_id)
    )
    for os in old_stage_ids:
        await database.execute(
            prize_draw_winners_table.delete()
            .where(prize_draw_winners_table.c.stage_id == os["id"])
        )
    await database.execute(
        prize_draw_stages_table.delete()
        .where(prize_draw_stages_table.c.draw_id == new_id)
    )

    # insert new stages & winners
    for order_idx, stage in enumerate(draw.stages):
        stage_id = await database.execute(
            prize_draw_stages_table.insert().values(
                draw_id=new_id,
                name=stage.name,
                description=stage.description,
                winners_count=stage.winnersCount,
                text_before=stage.textBefore,
                text_after=stage.textAfter,
                order_index=order_idx
            )
        )
        for winner in stage.winners:
            if isinstance(winner, dict):
                winner_name = winner.get("name")
                user_id = winner.get("user_id")
                r_id = winner.get("receipt_id")
            else:
                winner_name = str(winner)
                user_id = None
                r_id = None
            insert_values = {
                "stage_id": stage_id,
                "winner_name": winner_name,
            }
            if user_id is not None:
                insert_values["user_tg_id"] = user_id
            if HAS_PDW_RECEIPT_ID and r_id is not None:
                insert_values["receipt_id"] = r_id
            await database.execute(
                prize_draw_winners_table.insert().values(**insert_values)
            )

    return {"success": True, "id": new_id}


@app.delete("/prize-draws/{draw_id}")
async def delete_draw(draw_id: int):
    stage_ids = await database.fetch_all(
        sqlalchemy.select(prize_draw_stages_table.c.id).where(
            prize_draw_stages_table.c.draw_id == draw_id
        )
    )
    for sid in stage_ids:
        await database.execute(
            prize_draw_winners_table.delete().where(
                prize_draw_winners_table.c.stage_id == sid["id"]
            )
        )
    await database.execute(
        prize_draw_stages_table.delete().where(
            prize_draw_stages_table.c.draw_id == draw_id
        )
    )
    if has_receipt_draw_id():
        await database.execute(
            receipts_table.update()
            .where(receipts_table.c.draw_id == draw_id)
            .values(draw_id=None)
        )
    await database.execute(
        prize_draws_table.delete().where(prize_draws_table.c.id == draw_id)
    )
    return {"success": True}


class DetermineReq(BaseModel):
    winners_count: int


@app.post("/api/draw-stages/{stage_id}/determine")
async def api_determine_winners(stage_id: int, req: DetermineReq):
    stage_row = await database.fetch_one(
        prize_draw_stages_table.select().where(prize_draw_stages_table.c.id == stage_id)
    )
    if not stage_row:
        raise HTTPException(status_code=404, detail="Stage not found")

    join_clause = receipts_table.join(
        users_table, receipts_table.c.user_tg_id == users_table.c.tg_id
    ).outerjoin(
        participant_settings_table,
        participant_settings_table.c.user_tg_id == users_table.c.tg_id,
    )
    query = (
        sqlalchemy.select(
            receipts_table.c.id,
            receipts_table.c.user_tg_id,
            receipts_table.c.file_path,
            users_table.c.name.label("user_name"),
        )
        .select_from(join_clause)
        .where(receipts_table.c.draw_id == stage_row["draw_id"])
    )
    query = query.where(
        sqlalchemy.or_(
            participant_settings_table.c.blocked == False,
            participant_settings_table.c.blocked.is_(None),
        )
    )
    if has_receipt_status():
        query = query.where(
            receipts_table.c.status.in_(["Подтверждён", "Распознан"])
        )

    receipts_rows = await database.fetch_all(query)
    if not receipts_rows:
        raise HTTPException(status_code=400, detail="Нет чеков для розыгрыша")

    sample = list(receipts_rows)
    random.shuffle(sample)
    sample = sample[: max(1, req.winners_count)]

    await database.execute(
        prize_draw_winners_table.delete().where(
            prize_draw_winners_table.c.stage_id == stage_id
        )
    )

    winners_resp = []
    for r in sample:
        insert_values = {
            "stage_id": stage_id,
            "user_tg_id": r["user_tg_id"],
            "winner_name": r["user_name"],
        }
        if HAS_PDW_RECEIPT_ID:
            insert_values["receipt_id"] = r["id"]
        await database.execute(
            prize_draw_winners_table.insert().values(**insert_values)
        )
        fpath = r["file_path"]
        if fpath and not fpath.startswith("/static"):
            fpath = f"/static/uploads/{Path(fpath).name}"
        winners_resp.append(
            {
                "name": r["user_name"],
                "user_id": r["user_tg_id"],
                "file": fpath,
                **({"receipt_id": r["id"]} if HAS_PDW_RECEIPT_ID else {}),
            }
        )

    return {"winners": winners_resp}


def _format_winner_message(text_before: str | None, winners: list[str], text_after: str | None) -> str:
    parts = []
    if text_before:
        parts.append(text_before.strip())
    for idx, name in enumerate(winners, 1):
        parts.append(f"{idx}. {name}")
    if text_after:
        parts.append(text_after.strip())
    return "\n".join(parts)


async def _get_stage_winner_names(stage_id: int) -> list[str]:
    if HAS_PDW_RECEIPT_ID:
        query = (
            sqlalchemy.select(
                prize_draw_winners_table.c.winner_name,
                prize_draw_winners_table.c.user_tg_id,
                users_table.c.name.label("user_name"),
            )
            .select_from(
                prize_draw_winners_table.outerjoin(
                    users_table,
                    users_table.c.tg_id == prize_draw_winners_table.c.user_tg_id,
                )
            )
            .where(prize_draw_winners_table.c.stage_id == stage_id)
        )
    else:
        query = (
            sqlalchemy.select(
                prize_draw_winners_table.c.winner_name,
                prize_draw_winners_table.c.user_tg_id,
                users_table.c.name.label("user_name"),
            )
            .select_from(
                prize_draw_winners_table.outerjoin(
                    users_table,
                    users_table.c.tg_id == prize_draw_winners_table.c.user_tg_id,
                )
            )
            .where(prize_draw_winners_table.c.stage_id == stage_id)
        )
    rows = await database.fetch_all(query)
    return [r["user_name"] or r["winner_name"] for r in rows]


@app.post("/api/draw-stages/{stage_id}/test-mailing")
async def api_draw_stage_test_mailing(stage_id: int):
    stage = await database.fetch_one(
        prize_draw_stages_table.select().where(prize_draw_stages_table.c.id == stage_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    winners = await _get_stage_winner_names(stage_id)
    msg_text = _format_winner_message(stage["text_before"], winners, stage["text_after"])

    testers = await database.fetch_all(
        participant_settings_table.select().where(participant_settings_table.c.tester == True)
    )
    ids = [t["user_tg_id"] for t in testers]
    for uid in ids:
        try:
            await send_and_log_message(uid, msg_text)
        except Exception as e:
            print("draw test send error", e)
    return {"success": True}


@app.get("/api/notifications")
async def api_notifications():
    """Return receipts with problem receipts and unanswered questions."""
    notifications = []

    if has_receipt_status():
        problematic_statuses = [
            "Нет товара в чеке",
            "Ошибка",
            "Не распознан",
        ]
        rec_rows = await database.fetch_all(
            sqlalchemy.select(
                receipts_table.c.id,
                receipts_table.c.number,
                receipts_table.c.status,
            ).where(receipts_table.c.status.in_(problematic_statuses))
        )
        status_text = {
            "Нет товара в чеке": "нет нужного товара",
            "Ошибка": "ошибка обработки",
            "Не распознан": "не распознан",
        }
        for r in rec_rows:
            descr = status_text.get(r["status"], r["status"].lower())
            text = f"Чек {r['number'] or r['id']} – {descr}"
            notifications.append({
                "type": "receipt",
                "id": r["id"],
                "text": text,
            })

    q_rows = await database.fetch_all(
        sqlalchemy.select(
            questions_table.c.id,
            questions_table.c.text,
        ).where(questions_table.c.status == "Новый")
    )
    for q in q_rows:
        short = q["text"][:30] + ("…" if len(q["text"]) > 30 else "")
        text = f"Вопрос: {short}"
        notifications.append({
            "type": "question",
            "id": q["id"],
            "text": text,
        })

    return {"notifications": notifications}


@app.post("/api/draw-stages/{stage_id}/mailing")
async def api_draw_stage_mailing(stage_id: int):
    stage = await database.fetch_one(
        prize_draw_stages_table.select().where(prize_draw_stages_table.c.id == stage_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    winners = await _get_stage_winner_names(stage_id)
    msg_text = _format_winner_message(stage["text_before"], winners, stage["text_after"])

    users = await database.fetch_all(users_table.select())
    ids = [u["tg_id"] for u in users]
    for uid in ids:
        try:
            await send_and_log_message(uid, msg_text)
        except Exception as e:
            print("draw mailing send error", e)
    return {"success": True}


@app.get("/api/draw-stages/{stage_id}/export")
async def api_draw_stage_export(stage_id: int):
    stage = await database.fetch_one(
        prize_draw_stages_table.select().where(prize_draw_stages_table.c.id == stage_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    query = (
        sqlalchemy.select(
            prize_draw_winners_table.c.winner_name,
            prize_draw_winners_table.c.user_tg_id,
            users_table.c.name.label("user_name"),
            users_table.c.phone,
        )
        .select_from(
            prize_draw_winners_table.outerjoin(
                users_table,
                users_table.c.tg_id == prize_draw_winners_table.c.user_tg_id,
            )
        )
        .where(prize_draw_winners_table.c.stage_id == stage_id)
    )
    rows = await database.fetch_all(query)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Имя", "Telegram ID", "Телефон", "Ссылка на чат"])
    for r in rows:
        name = r["user_name"] or r["winner_name"]
        tg_id = r["user_tg_id"] or ""
        phone = r["phone"] or ""
        link = f"tg://user?id={tg_id}" if tg_id else ""
        writer.writerow([name, tg_id, phone, link])
    csv_data = output.getvalue()
    output.close()
    headers = {
        "Content-Disposition": f"attachment; filename=winners_stage_{stage_id}.csv"
    }
    return Response(csv_data, media_type="text/csv", headers=headers)


@app.get("/questions", response_class=HTMLResponse)
async def questions(request: Request):
    rows = await database.fetch_all(
        questions_table.select().order_by(questions_table.c.create_dt.desc())
    )
    user_ids = set()
    for r in rows:
        row = dict(r)
        uid = row.get("user_tg_id") or row.get("user_id")
        if uid:
            user_ids.add(uid)
    user_map = {}
    if user_ids:
        user_rows = await database.fetch_all(
            users_table.select().where(users_table.c.tg_id.in_(user_ids))
        )
        # key by stringified tg_id to avoid mismatches between int/str types
        user_map = {str(u["tg_id"]): u["name"] for u in user_rows}

    questions = []
    for r in rows:
        row = dict(r)
        user_id = row.get("user_tg_id") or row.get("user_id")
        name = user_map.get(str(user_id)) or "Пользователь"
        questions.append({
            "id": row.get("id"),
            "text": row.get("text", ""),
            "type": row.get("type", ""),
            "status": row.get("status", ""),
            "user": {"id": user_id, "name": name},
        })
    msgs = await database.fetch_all(
        question_messages_table.select().order_by(question_messages_table.c.timestamp)
    )
    messages_by_q = {}
    for m in msgs:
        qid = m["question_id"]
        is_answer = bool(m["is_answer"]) if HAS_QM_IS_ANSWER and "is_answer" in m else False
        messages_by_q.setdefault(qid, []).append({
            "sender": m["sender"],
            "text": m["text"],
            "is_answer": is_answer,
            "timestamp": m["timestamp"].isoformat(),
        })
    return templates.TemplateResponse(
        "questions.html",
        {
            "request": request,
            "active_page": "questions",
            "questions_data": questions,
            "messages_data": messages_by_q,
            "version": app.state.static_version,
        },
    )

@app.get("/api/questions")
async def api_get_questions(status: Optional[str] = None):
    query = questions_table.select()
    if status:
        query = query.where(questions_table.c.status == status)
    query = query.order_by(questions_table.c.create_dt.desc())
    rows = await database.fetch_all(query)
    user_ids = set()
    for r in rows:
        rd = dict(r)
        uid = rd.get("user_tg_id") or rd.get("user_id")
        if uid:
            user_ids.add(uid)
    user_map = {}
    if user_ids:
        user_rows = await database.fetch_all(
            users_table.select().where(users_table.c.tg_id.in_(user_ids))
        )
        user_map = {str(u["tg_id"]): u["name"] for u in user_rows}

    questions = []
    for r in rows:
        row = dict(r)
        user_id = row.get("user_tg_id") or row.get("user_id")
        name = user_map.get(str(user_id)) or "Пользователь"
        questions.append({
            "id": row.get("id"),
            "text": row.get("text", ""),
            "type": row.get("type", ""),
            "status": row.get("status", ""),
            "user": {"id": user_id, "name": name},
        })
    return {"questions": questions}


@app.get("/api/questions/{question_id}/messages")
async def api_get_question_messages(question_id: int):
    rows = await database.fetch_all(
        question_messages_table.select()
        .where(question_messages_table.c.question_id == question_id)
        .order_by(question_messages_table.c.timestamp)
    )
    messages = []
    for m in rows:
        is_answer = bool(m["is_answer"]) if HAS_QM_IS_ANSWER and "is_answer" in m else False
        messages.append({
            "sender": m["sender"],
            "text": m["text"],
            "is_answer": is_answer,
            "timestamp": m["timestamp"].isoformat(),
        })
    return {"messages": messages}

# === Загрузка медиафайлов для рассылок ===
@app.post("/api/media")
async def upload_media(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".avi", ".mkv"]:
        raise HTTPException(400, "Only photo and video files are allowed")
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / fname
    with dest.open("wb") as f:
        f.write(await file.read())
    return {"name": fname}


@app.delete("/api/media/{name}")
async def delete_media(name: str):
    dest = UPLOAD_DIR / name
    if dest.exists():
        dest.unlink()
    return {"success": True}

@app.get("/scheduled-messages", response_class=HTMLResponse)
async def scheduled_messages(request: Request):
    query = _scheduled_messages_select().order_by(
        scheduled_messages_table.c.schedule_dt.is_(None),
        scheduled_messages_table.c.schedule_dt,
    )
    rows = await database.fetch_all(query)
    messages = []
    now_utc = datetime.datetime.utcnow().replace(tzinfo=UTC)
    for record in rows:
        row = dict(record)
        schedule_val = _coerce_datetime(row.get("schedule_dt"))
        schedule_iso = ""
        schedule_display = ""
        if isinstance(schedule_val, datetime.datetime):
            aware = schedule_val if schedule_val.tzinfo else schedule_val.replace(tzinfo=UTC)
            schedule_iso = aware.astimezone(MSK_TZ).strftime("%Y-%m-%dT%H:%M")
            schedule_display = aware.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M")
        raw_media = row.get("media")
        try:
            media = json.loads(raw_media) if HAS_SM_MEDIA and raw_media else []
        except Exception:
            media = []
        status = _normalize_legacy_status(row.get("status")) or "Черновик"
        auto_flag = bool(row.get("auto_send") or 0) if HAS_SM_AUTO_SEND else False
        last_attempt_dt = _coerce_datetime(row.get("last_attempt_dt"))
        sent_dt = _coerce_datetime(row.get("sent_dt"))
        next_attempt_dt = _calc_next_attempt(
            auto_send=auto_flag,
            status=status,
            schedule_dt=schedule_val,
            last_attempt_dt=last_attempt_dt,
        )
        success_count = row.get("success_count")
        try:
            success_count = int(success_count) if success_count is not None else None
        except (TypeError, ValueError):
            success_count = None
        failure_count = row.get("failure_count")
        try:
            failure_count = int(failure_count) if failure_count is not None else None
        except (TypeError, ValueError):
            failure_count = None
        messages.append({
            "id": row["id"],
            "name": row["name"],
            "content": row["content"],
            "schedule": schedule_iso,
            "schedule_display": schedule_display,
            "status": status,
            "media": media,
            "auto_send": auto_flag,
            "last_attempt_display": _format_msk(last_attempt_dt),
            "sent_display": _format_msk(sent_dt),
            "next_attempt_display": _format_msk(next_attempt_dt),
            "is_overdue": bool(
                next_attempt_dt
                and (next_attempt_dt.replace(tzinfo=UTC) if next_attempt_dt.tzinfo is None else next_attempt_dt.astimezone(UTC))
                < now_utc
            ),
            "success_count": success_count,
            "failure_count": failure_count,
            "last_error": row.get("last_error") or "",
        })
    return templates.TemplateResponse(
        "scheduled_messages.html",
        {"request": request, "active_page": "scheduled_messages", "scheduled_data": messages, "version": app.state.static_version}
    )

class ScheduledMessageIn(BaseModel):
    id: Optional[int] = None
    name: str
    content: str
    schedule: Optional[datetime.datetime] = None
    status: Optional[str] = None
    auto_send: Optional[bool] = None
    media: Optional[List[Dict[str, str]]] = None


def _to_utc_naive(value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _coerce_datetime(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                if fmt is None:
                    return datetime.datetime.fromisoformat(value)
                return datetime.datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _format_msk(value: Optional[datetime.datetime]) -> str:
    if not value:
        return ""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(MSK_TZ).strftime("%d.%m.%Y %H:%M")


def _sanitize_status(value: Optional[str], default: str) -> str:
    if value in SCHEDULE_ALLOWED_STATUSES:
        return value
    return default


def _normalize_legacy_status(value: Optional[str]) -> Optional[str]:
    if value == "Новый":
        return "Черновик"
    if value == "Ожидает отправки":
        return "Запланирована"
    return value


def _determine_status(
    *,
    requested: Optional[str],
    auto_send: bool,
    schedule_dt: Optional[datetime.datetime],
    fallback: str,
) -> str:
    status = _sanitize_status(_normalize_legacy_status(requested), _normalize_legacy_status(fallback) or "Черновик")
    if auto_send and schedule_dt and status not in {"Отправлено", "Идёт отправка"}:
        status = "Запланирована"
    if not auto_send and status == "Запланирована":
        status = "Черновик"
    if status == "Идёт отправка" and not auto_send:
        status = "Черновик"
    return status


def _calc_next_attempt(
    *,
    auto_send: bool,
    status: str,
    schedule_dt: Optional[datetime.datetime],
    last_attempt_dt: Optional[datetime.datetime],
) -> Optional[datetime.datetime]:
    if not auto_send or status == "Отправлено":
        return None
    candidates: List[datetime.datetime] = []
    if schedule_dt:
        candidates.append(schedule_dt)
    if status == "Ошибка" and last_attempt_dt:
        candidates.append(last_attempt_dt + SCHEDULE_RETRY_INTERVAL)
    if not candidates:
        return None
    return max(candidates)


def _load_media_list(row: Dict[str, Any]) -> List[Dict[str, str]]:
    if not HAS_SM_MEDIA:
        return []
    raw = row.get("media")
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []


def _build_media_blueprint(media_list: List[Dict[str, str]]) -> List[Tuple[str, Optional[Path], Optional[str]]]:
    blueprint: List[Tuple[str, Optional[Path], Optional[str]]] = []
    for item in media_list[:10]:
        typ = item.get("type")
        name = item.get("file") or item.get("file_id")
        if typ not in ("photo", "video") or not name:
            continue
        local_path = UPLOAD_DIR / name
        if local_path.exists():
            blueprint.append((typ, local_path, None))
        else:
            blueprint.append((typ, None, name))
    return blueprint


def _instantiate_media(blueprint: List[Tuple[str, Optional[Path], Optional[str]]]) -> List[Tuple[str, object]]:
    media_payload: List[Tuple[str, object]] = []
    if not blueprint:
        return media_payload
    try:
        from aiogram.types import FSInputFile  # type: ignore
    except Exception:
        FSInputFile = None  # type: ignore
    for typ, path, file_id in blueprint:
        if path is not None and FSInputFile is not None:
            media_payload.append((typ, FSInputFile(path)))
        elif file_id:
            media_payload.append((typ, file_id))
    return media_payload


async def _broadcast_scheduled_message(
    message_id: int,
    row: Dict[str, Any],
    *,
    initiated_by_scheduler: bool = False,
) -> Tuple[int, int, Optional[str]]:
    users = await database.fetch_all(users_table.select())
    recipient_ids = []
    for u in users:
        row_user = dict(u)
        tg_id = row_user.get("tg_id")
        if tg_id:
            recipient_ids.append(tg_id)
    media_blueprint = _build_media_blueprint(_load_media_list(row))
    sent_count = 0
    failed_count = 0
    error_messages: List[str] = []
    has_recipients = bool(recipient_ids)
    if not recipient_ids:
        error_messages.append("Нет пользователей для рассылки")
        failed_count = max(failed_count, 1)
    for uid in recipient_ids:
        try:
            files = _instantiate_media(media_blueprint)
            await send_and_log_message(uid, row.get("content"), files if files else None)
            sent_count += 1
        except Exception as exc:
            failed_count += 1
            error_messages.append(str(exc))
    if recipient_ids and sent_count == 0 and failed_count == 0:
        # No exceptions were raised but nothing was sent
        error_messages.append("Не удалось отправить сообщения")
        failed_count = len(recipient_ids)
    combined_error: Optional[str] = None
    if error_messages:
        preview = "; ".join(error_messages[:3])
        if len(error_messages) > 3:
            preview += f" и ещё {len(error_messages) - 3}"
        combined_error = preview[:SCHEDULE_MAX_ERROR_LENGTH]
    status = "Отправлено" if sent_count > 0 else "Ошибка"
    if not has_recipients:
        status = "Ошибка"
    if status == "Отправлено":
        combined_error = None
    now = datetime.datetime.utcnow()
    auto_send_after = 1 if (HAS_SM_AUTO_SEND and bool(row.get("auto_send"))) else 0
    if not has_recipients or status == "Отправлено":
        auto_send_after = 0
    update_values: Dict[str, Any] = {
        "status": status,
        "last_attempt_dt": now,
        "updated_at": now,
        "success_count": sent_count,
        "failure_count": failed_count,
        "last_error": combined_error,
    }
    if HAS_SM_AUTO_SEND:
        update_values["auto_send"] = auto_send_after
    if status == "Отправлено":
        update_values["sent_dt"] = now
        update_values["last_error"] = None
    else:
        if HAS_SM_AUTO_SEND and initiated_by_scheduler and bool(row.get("auto_send")):
            update_values["auto_send"] = 1
        update_values.setdefault("sent_dt", row.get("sent_dt"))
    await database.execute(
        scheduled_messages_table.update()
        .where(scheduled_messages_table.c.id == message_id)
        .values(**update_values)
    )
    return sent_count, failed_count, combined_error


async def _process_due_scheduled_messages() -> None:
    if not (HAS_SM_AUTO_SEND and hasattr(scheduled_messages_table.c, "auto_send")):
        return
    now = datetime.datetime.utcnow()
    candidates: List[Dict[str, Any]] = []
    async with _schedule_lock:
        query = (
            _scheduled_messages_select()
            .where(scheduled_messages_table.c.auto_send == 1)
            .where(scheduled_messages_table.c.schedule_dt != None)
            .where(scheduled_messages_table.c.schedule_dt <= now)
            .where(scheduled_messages_table.c.status != "Отправлено")
            .where(scheduled_messages_table.c.status != "Идёт отправка")
        )
        rows = await database.fetch_all(query)
        for row in rows:
            row_map = dict(row)
            last_attempt = _coerce_datetime(row_map.get("last_attempt_dt"))
            if (
                row_map.get("status") == "Ошибка"
                and last_attempt
                and last_attempt + SCHEDULE_RETRY_INTERVAL > now
            ):
                continue
            await database.execute(
                scheduled_messages_table.update()
                .where(scheduled_messages_table.c.id == row_map["id"])
                .values(
                    status="Идёт отправка",
                    last_attempt_dt=now,
                    updated_at=now,
                    last_error=None,
                )
            )
            row_map["status"] = "Идёт отправка"
            row_map["last_attempt_dt"] = now
            candidates.append(row_map)
    for row in candidates:
        try:
            sent, failed, error = await _broadcast_scheduled_message(
                row["id"], row, initiated_by_scheduler=True
            )
            if error:
                logger.warning(
                    "Auto mailing %s finished with errors: %s", row["id"], error
                )
            else:
                logger.info(
                    "Auto mailing %s sent to %s users", row["id"], sent
                )
        except Exception:
            logger.exception("Auto mailing %s failed", row["id"])
            await database.execute(
                scheduled_messages_table.update()
                .where(scheduled_messages_table.c.id == row["id"])
                .values(
                    status="Ошибка",
                    last_error="Не удалось выполнить рассылку",
                    updated_at=datetime.datetime.utcnow(),
                )
            )


async def _scheduled_sender_loop() -> None:
    try:
        # allow the application to finish startup work
        await asyncio.sleep(5)
        while True:
            await _process_due_scheduled_messages()
            await asyncio.sleep(SCHEDULE_POLL_SECONDS)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Scheduled sender loop terminated unexpectedly")

@app.post("/scheduled-messages")
async def save_scheduled_message(msg: ScheduledMessageIn):
    safe_media = []
    if msg.media:
        for m in msg.media:
            typ = m.get("type")
            name = m.get("file") or m.get("file_id")
            if typ not in ("photo", "video") or not name:
                continue
            safe_media.append({"type": typ, "file": name})
    media_json = json.dumps(safe_media) if safe_media else None
    schedule_dt = _to_utc_naive(msg.schedule)
    auto_flag = bool(msg.auto_send) if (HAS_SM_AUTO_SEND and msg.auto_send is not None) else False
    if auto_flag and schedule_dt is None:
        auto_flag = False
    now = datetime.datetime.utcnow()
    if msg.id is None:
        status_value = _determine_status(
            requested=msg.status,
            auto_send=auto_flag,
            schedule_dt=schedule_dt,
            fallback="Черновик",
        )
        new_id = await database.execute(
            scheduled_messages_table.insert().values(
                name=msg.name,
                content=msg.content,
                schedule_dt=schedule_dt,
                status=status_value,
                **({"auto_send": 1 if auto_flag else 0} if HAS_SM_AUTO_SEND else {}),
                created_at=now,
                updated_at=now,
                **({"media": media_json} if HAS_SM_MEDIA else {}),
            )
        )
        return {"success": True, "id": new_id}
    else:
        existing = await database.fetch_one(
            _scheduled_messages_select().where(scheduled_messages_table.c.id == msg.id)
        )
        if not existing:
            raise HTTPException(404, "Message not found")
        existing_map = dict(existing)
        fields_set = getattr(msg, "__fields_set__", set())
        schedule_value = schedule_dt
        if "schedule" not in fields_set:
            schedule_value = _coerce_datetime(existing_map.get("schedule_dt"))
        auto_flag_existing = bool(existing_map.get("auto_send") or 0) if HAS_SM_AUTO_SEND else False
        if HAS_SM_AUTO_SEND and "auto_send" in fields_set:
            auto_flag = bool(msg.auto_send)
            if auto_flag and schedule_value is None:
                auto_flag = False
        else:
            auto_flag = auto_flag_existing
        status_value = _determine_status(
            requested=msg.status if "status" in fields_set else existing_map.get("status"),
            auto_send=auto_flag,
            schedule_dt=schedule_value,
            fallback=existing_map.get("status") or "Черновик",
        )
        update_values = {
            "name": msg.name,
            "content": msg.content,
            "status": status_value,
            "updated_at": now,
            **({"auto_send": 1 if auto_flag else 0} if HAS_SM_AUTO_SEND else {}),
            **({"media": media_json} if HAS_SM_MEDIA else {}),
        }
        if "schedule" in fields_set:
            update_values["schedule_dt"] = schedule_value
        await database.execute(
            scheduled_messages_table.update()
            .where(scheduled_messages_table.c.id == msg.id)
            .values(**update_values)
        )
        return {"success": True, "id": msg.id}

@app.delete("/scheduled-messages/{message_id}")
async def delete_scheduled_message(message_id: int):
    existing = await database.fetch_one(
        _scheduled_messages_select().where(scheduled_messages_table.c.id == message_id)
    )
    if not existing:
        raise HTTPException(404, "Message not found")
    await database.execute(
        scheduled_messages_table.delete().where(scheduled_messages_table.c.id == message_id)
    )
    return JSONResponse({"success": True})


@app.post("/scheduled-messages/{message_id}/test")
async def test_send_scheduled_message(message_id: int):
    msg = await database.fetch_one(
        _scheduled_messages_select().where(scheduled_messages_table.c.id == message_id)
    )
    if not msg:
        raise HTTPException(404, "Message not found")

    testers = await database.fetch_all(
        participant_settings_table.select().where(participant_settings_table.c.tester == True)
    )
    ids = [r["user_tg_id"] for r in testers]
    msg_map = dict(msg)
    media_blueprint = _build_media_blueprint(_load_media_list(msg_map))
    for uid in ids:
        try:
            files = _instantiate_media(media_blueprint)
            await send_and_log_message(uid, msg["content"], files if files else None)
        except Exception as e:
            print("send test error", e)
    return {"success": True}


@app.post("/scheduled-messages/{message_id}/send")
async def send_scheduled_message(message_id: int):
    msg = await database.fetch_one(
        _scheduled_messages_select().where(scheduled_messages_table.c.id == message_id)
    )
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg["status"] == "Идёт отправка":
        raise HTTPException(409, "Mailing is already in progress")
    msg_map = dict(msg)
    sent, failed, error_text = await _broadcast_scheduled_message(message_id, msg_map)
    if error_text:
        logger.warning("Scheduled mailing %s finished with errors: %s", message_id, error_text)
    return {"success": True, "sent": sent, "failed": failed}


@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    row = await database.fetch_one(
        params_table.select()
        .where(params_table.c.user_tg_id == 0)
        .where(params_table.c.param_name == "product_keywords")
    )
    keywords = row["value"] if row else ""
    row_file = await database.fetch_one(
        params_table.select()
        .where(params_table.c.user_tg_id == 0)
        .where(params_table.c.param_name == "privacy_policy_file")
    )
    policy_url = row_file["value"] if row_file else ""
    row_rules = await database.fetch_one(
        params_table.select()
        .where(params_table.c.user_tg_id == 0)
        .where(params_table.c.param_name == "RULE_PDF")
    )
    rules_url = row_rules["value"] if row_rules else ""
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
            "keywords": keywords,
            "policy_url": policy_url,
            "rules_url": rules_url,
            "version": app.state.static_version,
        },
    )


@app.post("/settings")
async def save_settings(
    product_names: str = Form(""),
    privacy_file: UploadFile | None = File(None),
    rules_file: UploadFile | None = File(None),
):
    query = sqlite_insert(params_table).values(
        user_tg_id=0, param_name="product_keywords", value=product_names
    )
    query = query.on_conflict_do_update(
        index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
        set_={"value": product_names},
    )
    await database.execute(query)
    async def _save_upload(upload: UploadFile, prefix: str, param_name: str) -> None:
        suffix = Path(upload.filename).suffix
        fname = f"{prefix}_{uuid.uuid4().hex}{suffix}"
        dest = UPLOAD_DIR / fname
        with open(dest, "wb") as out:
            out.write(await upload.read())
        rel = f"/static/uploads/{fname}"
        query = sqlite_insert(params_table).values(
            user_tg_id=0, param_name=param_name, value=rel
        )
        query = query.on_conflict_do_update(
            index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
            set_={"value": rel},
        )
        await database.execute(query)

    if privacy_file and privacy_file.filename:
        await _save_upload(privacy_file, "privacy", "privacy_policy_file")
    if rules_file and rules_file.filename:
        await _save_upload(rules_file, "rules", "RULE_PDF")
    return RedirectResponse("/settings", status_code=303)

@app.get("/participants", response_class=HTMLResponse)
async def participants(request: Request):
    users_rows = await database.fetch_all(users_table.select())
    settings_rows = await database.fetch_all(participant_settings_table.select())
    settings_map = {
        r["user_tg_id"]: {"blocked": bool(r["blocked"]), "tester": bool(r["tester"])}
        for r in settings_rows
    }
    
    participants = []
    for u in users_rows:
        s = settings_map.get(u["tg_id"], {"blocked": False, "tester": False})
        participants.append({
            "id": u["tg_id"],
            "name": u["name"],
            "phone": u["phone"],
            "telegramId": u["tg_id"],
            "createdAt": u["create_dt"].isoformat(),
            "blocked": s["blocked"],
            "tester": s["tester"]
        })
    return templates.TemplateResponse(
        "participants.html",
        {
            "request": request,
            "active_page": "participants",
            "participants_data": participants,
            "version": app.state.static_version,
        },
    )

class ParticipantUpdate(BaseModel):
    name: str
    phone: str
    blocked: bool
    tester: bool

@app.post("/participants/{tg_id}")
async def update_participant(tg_id: int, data: ParticipantUpdate):
    await database.execute(
        users_table.update()
        .where(users_table.c.tg_id == tg_id)
        .values(name=data.name, phone=data.phone)
    )
    exists = await database.fetch_one(
        participant_settings_table.select().where(participant_settings_table.c.user_tg_id == tg_id)
    )
    if exists:
        await database.execute(
            participant_settings_table.update()
            .where(participant_settings_table.c.user_tg_id == tg_id)
            .values(blocked=data.blocked, tester=data.tester)
        )
    else:
        await database.execute(
            participant_settings_table.insert().values(
                user_tg_id=tg_id, blocked=data.blocked, tester=data.tester
            )
        )
    return {"success": True}


@app.get("/participants/export")
async def export_participants():
    users_rows = await database.fetch_all(
        users_table.select().order_by(users_table.c.create_dt)
    )
    user_settings_rows = await database.fetch_all(user_settings_table.select())
    participant_settings_rows = await database.fetch_all(participant_settings_table.select())
    user_extended_rows = await database.fetch_all(user_extended_table.select())
    user_params_rows = await database.fetch_all(user_params_table.select())
    params_rows = await database.fetch_all(params_table.select())
    params_site_rows = await database.fetch_all(params_site_table.select())

    def normalize(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, datetime.datetime):
            return value.replace(microsecond=0).isoformat(sep=" ")
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, datetime.time):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.hex()
        return str(value)

    def build_params_map(records, key_name):
        result = {}
        for record in records:
            row = dict(record)
            user_id = row.get(key_name)
            if user_id is None:
                continue
            name = row.get("param_name")
            value = normalize(row.get("value"))
            entry = f"{name}={value}" if name else value
            result.setdefault(user_id, []).append(entry)
        return result

    user_settings_map = {
        row["tg_id"]: dict(row)
        for row in user_settings_rows
        if row["tg_id"] is not None
    }
    participant_settings_map = {
        row["user_tg_id"]: dict(row)
        for row in participant_settings_rows
        if row["user_tg_id"] is not None
    }
    user_extended_map = {
        row["tg_id"]: dict(row)
        for row in user_extended_rows
        if row["tg_id"] is not None
    }
    user_params_map = {
        row["user_tg_id"]: dict(row)
        for row in user_params_rows
        if row["user_tg_id"] is not None
    }
    params_map = build_params_map(params_rows, "user_tg_id")
    params_site_map = build_params_map(params_site_rows, "user_tg_id")

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "tg_id",
        "name",
        "age_18",
        "phone",
        "create_dt",
        "subscription",
        "username",
        "extended_all_data",
        "extended_create_dt",
        "blocked",
        "tester",
        "participant_settings_create_dt",
        "last_message_id",
        "last_image_message_list",
        "user_params_create_dt",
        "params_site",
        "params",
    ])

    for record in users_rows:
        row = dict(record)
        user_id = row.get("tg_id")
        user_settings = user_settings_map.get(user_id, {})
        participant_settings = participant_settings_map.get(user_id, {})
        user_extended = user_extended_map.get(user_id, {})
        user_params = user_params_map.get(user_id, {})
        params_site_values = "; ".join(params_site_map.get(user_id, []))
        params_values = "; ".join(params_map.get(user_id, []))

        writer.writerow([
            normalize(row.get("tg_id")),
            normalize(row.get("name")),
            normalize(row.get("age_18")),
            normalize(row.get("phone")),
            normalize(row.get("create_dt")),
            normalize(user_settings.get("subscription")),
            normalize(user_extended.get("username")),
            normalize(user_extended.get("all_data")),
            normalize(user_extended.get("create_dt")),
            normalize(participant_settings.get("blocked")),
            normalize(participant_settings.get("tester")),
            normalize(participant_settings.get("create_dt")),
            normalize(user_params.get("last_message_id")),
            normalize(user_params.get("last_image_message_list")),
            normalize(user_params.get("create_dt")),
            normalize(params_site_values),
            normalize(params_values),
        ])

    csv_data = output.getvalue()
    output.close()
    filename = f"participants_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename}"
    }
    return Response(csv_data, media_type="text/csv; charset=utf-8", headers=headers)

@app.get("/receipts", response_class=HTMLResponse)
async def receipts(request: Request):
    sel_columns = [receipts_table, users_table.c.name.label("user_name")]
    join_clause = receipts_table.outerjoin(
        users_table, receipts_table.c.user_tg_id == users_table.c.tg_id
    )
    if has_receipt_draw_id():
        sel_columns.append(prize_draws_table.c.title.label("draw_title"))
        join_clause = join_clause.outerjoin(
            prize_draws_table, receipts_table.c.draw_id == prize_draws_table.c.id
        )
    query = (
        sqlalchemy.select(*sel_columns)
        .select_from(join_clause)
        .order_by(receipts_table.c.id.desc())
    )
    rows = await database.fetch_all(query)
    receipts: list[dict] = []
    for row in rows:
        r = dict(row)
        rid = r["id"]
        # иногда в таблице могут остаться записи без ID из-за некорректных вставок
        # такие записи нельзя корректно обрабатывать через API, поэтому пропускаем их
        if rid is None:
            continue
        file_path = r["file_path"]
        if file_path and not str(file_path).startswith("/static"):
            file_path = f"/static/uploads/{Path(file_path).name}"
        created_at = r.get("create_dt")
        if isinstance(created_at, (datetime.date, datetime.datetime)):
            created_at = created_at.isoformat()
        elif created_at is not None:
            created_at = str(created_at)
        receipts.append(
            {
                "id": rid,
                "number": r.get("number"),
                "created_at": created_at,
                "user_tg_id": r.get("user_tg_id"),
                "user_name": r.get("user_name"),
                "file_path": file_path,
                "status": r.get("status") if has_receipt_status() else None,
                "draw_id": r.get("draw_id") if has_receipt_draw_id() else None,
                "draw_title": r.get("draw_title"),
                "comment": r.get("comment") if has_receipt_comment() else None,
            }
        )
    draw_query = sqlalchemy.select(prize_draws_table.c.id, prize_draws_table.c.title)
    draws_rows = await database.fetch_all(draw_query)
    draws = [{"id": d["id"], "title": d["title"]} for d in draws_rows]
    return templates.TemplateResponse(
        "receipts.html",
        {
            "request": request,
            "active_page": "receipts",
            "receipts_data": receipts,
            "draws_data": draws,
            "version": app.state.static_version,
        }
    )

@app.get("/api/receipts/{receipt_id}")
async def get_receipt(receipt_id: int):
    sel_cols = [receipts_table, users_table.c.name.label("user_name")]
    join_clause = receipts_table.outerjoin(
        users_table, receipts_table.c.user_tg_id == users_table.c.tg_id
    )
    if has_receipt_draw_id():
        sel_cols.append(prize_draws_table.c.title.label("draw_title"))
        join_clause = join_clause.outerjoin(
            prize_draws_table, receipts_table.c.draw_id == prize_draws_table.c.id
        )
    query = (
        sqlalchemy.select(*sel_cols)
        .select_from(join_clause)
        .where(receipts_table.c.id == receipt_id)
    )
    r = await database.fetch_one(query)
    if not r:
        raise HTTPException(404, "Receipt not found")
    r = dict(r)
    file_path = r["file_path"]
    if file_path and not str(file_path).startswith("/static"):
        file_path = f"/static/uploads/{Path(file_path).name}"
    created_at = r.get("create_dt")
    if isinstance(created_at, (datetime.date, datetime.datetime)):
        created_at = created_at.isoformat()
    elif created_at is not None:
        created_at = str(created_at)
    return {
        "id": r["id"],
        "number": r.get("number"),
        "created_at": created_at,
        "amount": r.get("amount"),
        "user_tg_id": r.get("user_tg_id"),
        "user_name": r.get("user_name"),
        "file_path": file_path,
        "status": r.get("status") if has_receipt_status() else None,
        "message_id": r.get("message_id") if has_receipt_msg_id() else None,
        "draw_id": r.get("draw_id") if has_receipt_draw_id() else None,
        "draw_title": r.get("draw_title"),
        "comment": r.get("comment") if has_receipt_comment() else None,
    }

class ReceiptUpdate(BaseModel):
    status: str
    draw_id: Optional[int] = None
    comment: Optional[str] = None

@app.post("/api/receipts/{receipt_id}")
async def update_receipt(receipt_id: int, upd: ReceiptUpdate):
    old_row = await database.fetch_one(
        receipts_table.select().where(receipts_table.c.id == receipt_id)
    )
    update_values = {"status": upd.status}
    if has_receipt_draw_id():
        update_values["draw_id"] = upd.draw_id

    manual_comment_note = "Изменено пользователем"
    comment_value = (upd.comment or "").strip()
    if has_receipt_comment():
        if manual_comment_note.lower() not in comment_value.lower():
            if comment_value:
                comment_value = f"{comment_value} ({manual_comment_note})"
            else:
                comment_value = manual_comment_note
        update_values["comment"] = comment_value
    await database.execute(
        receipts_table.update()
        .where(receipts_table.c.id == receipt_id)
        .values(**update_values)
    )
    if old_row and has_receipt_status() and has_receipt_msg_id():
        if hasattr(old_row, "_mapping"):
            row_data = dict(old_row._mapping)
        else:
            row_data = dict(old_row)
        if row_data.get("status") != upd.status:
            message_id = row_data.get("message_id")
            user_tg_id = row_data.get("user_tg_id")
            if message_id and user_tg_id:
                bot = get_bot()
                if not bot:
                    logger.warning(
                        "Receipt %s status changed to %s but bot token is unavailable",
                        receipt_id,
                        upd.status,
                    )
                else:
                    status_messages = {
                        "Подтверждён": "✅ Чек подтверждён",
                        "Нет товара в чеке": "❌ В чеке не найден нужный товар",
                    }
                    text = status_messages.get(upd.status)
                    if text:
                        try:
                            await bot.send_message(
                                user_tg_id,
                                text,
                                reply_to_message_id=message_id,
                            )
                            log_values = {
                                "user_tg_id": user_tg_id,
                                "sender": "admin",
                                "text": text,
                                "buttons": None,
                                "media": None,
                            }
                            if HAS_PM_IS_ANSWER:
                                log_values["is_answer"] = True
                            await database.execute(
                                participant_messages_table.insert().values(**log_values)
                            )
                        except Exception:
                            logger.exception(
                                "Failed to send receipt status message for receipt %s",
                                receipt_id,
                            )
    return {"success": True}

@app.delete("/api/receipts/{receipt_id}")
async def delete_receipt(receipt_id: int):
    row = await database.fetch_one(
        receipts_table.select().where(receipts_table.c.id == receipt_id)
    )
    if not row:
        raise HTTPException(404, "Receipt not found")
    file_path = row["file_path"]
    if file_path:
        upload_dir = Path(__file__).resolve().parent / "static" / "uploads"
        fpath = upload_dir / Path(str(file_path)).name
        try:
            fpath.unlink()
        except FileNotFoundError:
            pass
    if HAS_PDW_RECEIPT_ID:
        await database.execute(
            prize_draw_winners_table.delete().where(
                prize_draw_winners_table.c.receipt_id == receipt_id
            )
        )
    await database.execute(
        notifications_table.delete().where(
            notifications_table.c.message.like(f"%{receipt_id}%")
        )
    )
    await database.execute(
        receipts_table.delete().where(receipts_table.c.id == receipt_id)
    )
    return JSONResponse({"success": True})

async def get_participant_messages(
    user_tg_id: int,
    include_deleted: bool = False
) -> List[Dict]:
    """
    Возвращает для данного user_tg_id список сообщений из participant_messages,
    парся JSON-поля buttons/media и отфильтровывая по is_deleted.
    """
    query = participant_messages_table.select().where(
        participant_messages_table.c.user_tg_id == user_tg_id
    )
    if not include_deleted:
        query = query.where(participant_messages_table.c.is_deleted == False)
    query = query.order_by(participant_messages_table.c.timestamp)

    rows = await database.fetch_all(query)

    result = []
    for m in rows:
        # парсим JSON-поля, если они непустые
        try:
            buttons = json.loads(m["buttons"]) if m["buttons"] else []
        except json.JSONDecodeError:
            buttons = []
        try:
            media = json.loads(m["media"]) if m["media"] else []
        except json.JSONDecodeError:
            media = []

        is_answer = bool(m["is_answer"]) if HAS_PM_IS_ANSWER and "is_answer" in m else False
        result.append({
            "id":         m["id"],
            "sender":     m["sender"],
            "text":       m["text"] or "",
            "isAnswer":   is_answer,
            "timestamp":  m["timestamp"].isoformat(),
            "is_deleted": bool(m["is_deleted"]),
            "buttons":    buttons,
            "media":      media,
        })
    return result

@app.get("/api/participants/{user_tg_id}/messages")
async def api_get_messages(user_tg_id: int, include_deleted: bool = False):
    return {"messages": await get_participant_messages(user_tg_id, include_deleted)}

@app.delete("/api/participants/messages/{message_id}")
async def api_delete_message(message_id: int):
    # можно проверить существование, но sqlite UPDATE без ошибок
    await mark_message_deleted(message_id)
    return {"success": True}

@app.post("/get_settings_site_all")
async def get_settings_site_all(request: Request):
    rows = await database.fetch_all(
        params_table.select().where(params_table.c.user_tg_id == 0)
    )
    data = {r["param_name"]: r["value"] for r in rows}
    return {
        "settings_site": {
            "min_amount": data.get("min_amount", ""),
            "PAYMENTS_TOKEN": data.get("PAYMENTS_TOKEN", ""),
            "privacy_policy_file": data.get("privacy_policy_file", ""),
            "RULE_PDF": data.get("RULE_PDF", ""),
        }
    }


@app.post("/update_settings_site")
async def update_settings_site(
    user_id: int = Form(...),
    min_order: str = Form(""),
    payment_token: str = Form(""),
    privacy_file: UploadFile | None = File(None),
    rules_file: UploadFile | None = File(None),
):
    for name, value in (("min_amount", min_order), ("PAYMENTS_TOKEN", payment_token)):
        if value:
            query = sqlite_insert(params_table).values(
                user_tg_id=0, param_name=name, value=value
            )
            query = query.on_conflict_do_update(
                index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
                set_={"value": value},
            )
            await database.execute(query)
    async def _save_upload(upload: UploadFile, prefix: str, param_name: str) -> None:
        suffix = Path(upload.filename).suffix
        fname = f"{prefix}_{uuid.uuid4().hex}{suffix}"
        dest = UPLOAD_DIR / fname
        with open(dest, "wb") as out:
            out.write(await upload.read())
        rel = f"/static/uploads/{fname}"
        query = sqlite_insert(params_table).values(
            user_tg_id=0, param_name=param_name, value=rel
        )
        query = query.on_conflict_do_update(
            index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
            set_={"value": rel},
        )
        await database.execute(query)

    if privacy_file and privacy_file.filename:
        await _save_upload(privacy_file, "privacy", "privacy_policy_file")
    if rules_file and rules_file.filename:
        await _save_upload(rules_file, "rules", "RULE_PDF")
    return {"success": True}


telegram_bot_token = globals().get("TG_BOT") or os.getenv("TG_BOT")
if not telegram_bot_token:
    raise RuntimeError("TG_BOT token is not set")

_bot = None


def get_bot():
    global _bot
    if _bot is None:
        try:
            from aiogram import Bot
            from aiogram.enums import ParseMode
            from aiogram.client.default import DefaultBotProperties
        except Exception as e:  # pragma: no cover - aiogram optional
            print("ERROR: aiogram import failed", e)
            return None
        _bot = Bot(telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return _bot


async def send_and_log_message(
    user_id: int,
    text: Optional[str] = None,
    media: Optional[List[Tuple[str, object]]] = None,
):
    """Send a message via the bot and log it to participant_messages."""
    bot = get_bot()
    if not bot:
        return

    from aiogram.types import InputMediaPhoto, InputMediaVideo  # type: ignore

    sent_messages = []
    files_info: List[Dict[str, Any]] = []
    if not media:
        if text:
            msg = await bot.send_message(user_id, text)
            sent_messages.append(msg)
        else:
            return
    elif len(media) == 1:
        typ, fobj = media[0]
        if typ == "photo":
            msg = await bot.send_photo(user_id, fobj, caption=text or None)
            files_info.append({"type": "photo", "file_id": msg.photo[-1].file_id})
        else:
            msg = await bot.send_video(user_id, fobj, caption=text or None)
            files_info.append({"type": "video", "file_id": msg.video.file_id})
        sent_messages.append(msg)
    else:
        media_group = []
        for i, (typ, fobj) in enumerate(media):
            caption = text if i == 0 else None
            if typ == "photo":
                media_group.append(InputMediaPhoto(media=fobj, caption=caption))
            else:
                media_group.append(InputMediaVideo(media=fobj, caption=caption))
        msgs = await bot.send_media_group(user_id, media_group)
        sent_messages.extend(msgs)
        for m in msgs:
            if m.photo:
                files_info.append({"type": "photo", "file_id": m.photo[-1].file_id})
            elif m.video:
                files_info.append({"type": "video", "file_id": m.video.file_id})

    values = {
        "user_tg_id": user_id,
        "sender": "admin",
        "text": text or "",
        "buttons": None,
        "media": json.dumps(files_info) if files_info else None,
    }
    if HAS_PM_IS_ANSWER:
        values["is_answer"] = False
    new_id = await database.execute(
        participant_messages_table.insert().values(**values)
    )
    return sent_messages, new_id


@app.get("/api/file/{file_id}")
async def proxy_file(file_id: str):
    """
    Перенаправляем клиент на URL файла в Telegram CDN.
    """
    # Получаем метаданные файла у Telegram
    if not file_id or file_id == "undefined":
        raise HTTPException(status_code=400, detail="File ID is required")
    
    bot = get_bot()
    if not bot:
        raise HTTPException(status_code=500, detail="Bot is not configured")

    file = await bot.get_file(file_id)
    file_path = file.file_path  # например: "photos/file_123.jpg"
    url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"

    # Перенаправляем браузер на этот URL
    return RedirectResponse(url)


class SendMessageIn(BaseModel):
    text: str
    is_answer: bool | None = None

@app.post("/api/participants/{user_tg_id}/messages")
async def api_send_message(user_tg_id: int, msg_in: SendMessageIn):
    try:
        sent, new_id = await send_and_log_message(user_tg_id, msg_in.text)
    except Exception as e:
        raise HTTPException(500, f"Telegram error: {e}")

    msg_obj = sent[0] if sent else None
    ts = msg_obj.date.isoformat() if msg_obj else datetime.datetime.utcnow().isoformat()

    return {
        "success": True,
        "id": new_id,
        "text": msg_in.text,
        "timestamp": ts
    }


class AnswerIn(BaseModel):
    text: str

class QuestionUpdate(BaseModel):
    status: str


@app.post("/api/questions/{question_id}/answer")
async def answer_question(question_id: int, ans: AnswerIn):
    q = await database.fetch_one(
        questions_table.select().where(questions_table.c.id == question_id)
    )
    if not q:
        raise HTTPException(404, "Question not found")

    try:
        sent_list, _ = await send_and_log_message(q["user_tg_id"], ans.text)
    except Exception as e:
        raise HTTPException(500, f"Telegram error: {e}")
    sent = sent_list[0] if sent_list else None

    qmsg_values = {
        "question_id": question_id,
        "sender": "admin",
        "text": ans.text,
    }
    if HAS_QM_IS_ANSWER:
        qmsg_values["is_answer"] = True
    await database.execute(
        question_messages_table.insert().values(**qmsg_values)
    )

    await database.execute(
        questions_table.update()
        .where(questions_table.c.id == question_id)
        .values(status="Отвечено")
    )

    ts = sent.date.isoformat() if sent else datetime.datetime.utcnow().isoformat()
    return {
        "success": True,
        "timestamp": ts,
        "is_answer": True
    }


@app.post("/api/questions/{question_id}")
async def update_question(question_id: int, upd: QuestionUpdate):
    q = await database.fetch_one(
        questions_table.select().where(questions_table.c.id == question_id)
    )
    if not q:
        raise HTTPException(404, "Question not found")
    await database.execute(
        questions_table.update()
        .where(questions_table.c.id == question_id)
        .values(status=upd.status)
    )
    return {"success": True}
