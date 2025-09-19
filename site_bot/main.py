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
from typing import List, Optional, Dict, Any, Tuple
import datetime
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import logging

# Админ-панель через SQLAdmin
from sqladmin import Admin, ModelView
import json
import os
import uuid
from pathlib import Path
import random
import csv
import io
from decimal import Decimal

from sql_mgt import ensure_receipt_comment_column_sync

# aiogram is imported lazily when sending messages

# ==============================
# Настройка БД
# ==============================
DATABASE_URL = "sqlite:///../../tg_base.sqlite"

database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()
logger = logging.getLogger(__name__)


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
scheduled_messages_table   = Table("scheduled_messages", metadata, autoload_with=engine)
prize_draws_table          = Table("prize_draws", metadata, autoload_with=engine)
prize_draw_stages_table    = Table("prize_draw_stages", metadata, autoload_with=engine)
prize_draw_winners_table   = Table("prize_draw_winners", metadata, autoload_with=engine)
participant_settings_table = Table("participant_settings", metadata, autoload_with=engine)
participant_messages_table = Table("participant_messages", metadata, autoload_with=engine)

# Some deployments may still use an older database schema without the
# `is_answer` column.  Detect its presence so we can behave gracefully
# when reading or writing data.
HAS_PM_IS_ANSWER = 'is_answer' in participant_messages_table.c
HAS_QM_IS_ANSWER = 'is_answer' in question_messages_table.c
HAS_SM_MEDIA = 'media' in scheduled_messages_table.c
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

# def has_receipt_comment() -> bool:
#     """Return True if the receipts table has a 'comment' column."""
#     return 'comment' in receipts_table.c

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

@app.on_event("shutdown")
async def on_shutdown():
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
    rows = await database.fetch_all(scheduled_messages_table.select())
    messages = []
    for r in rows:
        schedule_val = r["schedule_dt"]
        if schedule_val is not None:
            schedule_str = schedule_val.strftime("%Y-%m-%dT%H:%M")
        else:
            schedule_str = ""
        try:
            media = json.loads(r["media"]) if HAS_SM_MEDIA and r["media"] else []
        except Exception:
            media = []
        messages.append({
            "id": r["id"],
            "name": r["name"],
            "content": r["content"],
            "schedule": schedule_str,
            "status": r["status"],
            "media": media,
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
    status: Optional[str] = "Новый"
    media: Optional[List[Dict[str, str]]] = None

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
    if msg.id is None:
        new_id = await database.execute(
            scheduled_messages_table.insert().values(
                name=msg.name,
                content=msg.content,
                schedule_dt=msg.schedule or datetime.datetime.utcnow(),
                status=msg.status,
                **({"media": media_json} if HAS_SM_MEDIA else {})
            )
        )
        return {"success": True, "id": new_id}
    else:
        existing = await database.fetch_one(
            scheduled_messages_table.select().where(scheduled_messages_table.c.id == msg.id)
        )
        if not existing:
            raise HTTPException(404, "Message not found")
        await database.execute(
            scheduled_messages_table.update()
            .where(scheduled_messages_table.c.id == msg.id)
            .values(
                name=msg.name,
                content=msg.content,
                schedule_dt=msg.schedule or datetime.datetime.utcnow(),
                status=msg.status,
                **({"media": media_json} if HAS_SM_MEDIA else {})
            )
        )
        return {"success": True, "id": msg.id}

@app.delete("/scheduled-messages/{message_id}")
async def delete_scheduled_message(message_id: int):
    existing = await database.fetch_one(
        scheduled_messages_table.select().where(scheduled_messages_table.c.id == message_id)
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
        scheduled_messages_table.select().where(scheduled_messages_table.c.id == message_id)
    )
    if not msg:
        raise HTTPException(404, "Message not found")

    testers = await database.fetch_all(
        participant_settings_table.select().where(participant_settings_table.c.tester == True)
    )
    ids = [r["user_tg_id"] for r in testers]
    media = []
    if HAS_SM_MEDIA:
        try:
            media = json.loads(msg["media"]) if msg["media"] else []
        except Exception:
            media = []
    for uid in ids:
        try:
            files = []
            for m in media[:10]:
                typ = m.get("type")
                fname = m.get("file") or m.get("file_id")
                if typ not in ("photo", "video") or not fname:
                    continue
                local = UPLOAD_DIR / fname
                from aiogram.types import FSInputFile  # type: ignore
                obj = FSInputFile(local) if local.exists() else fname
                files.append((typ, obj))

            await send_and_log_message(uid, msg["content"], files if files else None)
        except Exception as e:
            print("send test error", e)
    return {"success": True}


@app.post("/scheduled-messages/{message_id}/send")
async def send_scheduled_message(message_id: int):
    msg = await database.fetch_one(
        scheduled_messages_table.select().where(scheduled_messages_table.c.id == message_id)
    )
    if not msg:
        raise HTTPException(404, "Message not found")

    users = await database.fetch_all(users_table.select())
    ids = [u["tg_id"] for u in users]

    media = []
    if HAS_SM_MEDIA:
        try:
            media = json.loads(msg["media"]) if msg["media"] else []
        except Exception:
            media = []

    for uid in ids:
        try:
            files = []
            for m in media[:10]:
                typ = m.get("type")
                fname = m.get("file") or m.get("file_id")
                if typ not in ("photo", "video") or not fname:
                    continue
                local = UPLOAD_DIR / fname
                from aiogram.types import FSInputFile  # type: ignore
                obj = FSInputFile(local) if local.exists() else fname
                files.append((typ, obj))

            await send_and_log_message(uid, msg["content"], files if files else None)
        except Exception as e:
            print("send mailing error", e)

    now = datetime.datetime.utcnow()
    await database.execute(
        scheduled_messages_table.update()
        .where(scheduled_messages_table.c.id == message_id)
        .values(schedule_dt=now, status="Отправлено")
    )
    return {"success": True}


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
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
            "keywords": keywords,
            "policy_url": policy_url,
            "version": app.state.static_version,
        },
    )


@app.post("/settings")
async def save_settings(
    product_names: str = Form(""),
    privacy_file: UploadFile | None = File(None),
):
    query = sqlite_insert(params_table).values(
        user_tg_id=0, param_name="product_keywords", value=product_names
    )
    query = query.on_conflict_do_update(
        index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
        set_={"value": product_names},
    )
    await database.execute(query)
    if privacy_file and privacy_file.filename:
        fname = f"privacy_{uuid.uuid4().hex}{Path(privacy_file.filename).suffix}"
        dest = UPLOAD_DIR / fname
        with open(dest, "wb") as out:
            out.write(await privacy_file.read())
        rel = f"/static/uploads/{fname}"
        query = sqlite_insert(params_table).values(
            user_tg_id=0, param_name="privacy_policy_file", value=rel
        )
        query = query.on_conflict_do_update(
            index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
            set_={"value": rel},
        )
        await database.execute(query)
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
    }

class ReceiptUpdate(BaseModel):
    status: str
    draw_id: Optional[int] = None

@app.post("/api/receipts/{receipt_id}")
async def update_receipt(receipt_id: int, upd: ReceiptUpdate):
    old_row = await database.fetch_one(
        receipts_table.select().where(receipts_table.c.id == receipt_id)
    )
    update_values = {"status": upd.status}
    if has_receipt_draw_id():
        update_values["draw_id"] = upd.draw_id
    await database.execute(
        receipts_table.update()
        .where(receipts_table.c.id == receipt_id)
        .values(**update_values)
    )
    if (
        old_row
        and has_receipt_status()
        and old_row.get("status") != upd.status
        and has_receipt_msg_id()
    ):
        if old_row.get("message_id") and old_row.get("user_tg_id"):
            text = None
            status_messages = {
                "Подтверждён": "Чек подтверждён",
                "Нет товара в чеке": "В чеке не найден нужный товар",
            }
            text = status_messages.get(upd.status)
            if text:
                try:
                    await bot.send_message(
                        old_row["user_tg_id"],
                        text,
                        reply_to_message_id=old_row["message_id"],
                    )
                    log_values = {
                        "user_tg_id": old_row["user_tg_id"],
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
                except Exception as e:
                    print(f"Failed to send receipt status message: {e}")
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
        }
    }


@app.post("/update_settings_site")
async def update_settings_site(
    user_id: int = Form(...),
    min_order: str = Form(""),
    payment_token: str = Form(""),
    privacy_file: UploadFile | None = File(None),
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
    if privacy_file and privacy_file.filename:
        fname = f"privacy_{uuid.uuid4().hex}{Path(privacy_file.filename).suffix}"
        dest = UPLOAD_DIR / fname
        with open(dest, "wb") as out:
            out.write(await privacy_file.read())
        rel = f"/static/uploads/{fname}"
        query = sqlite_insert(params_table).values(
            user_tg_id=0, param_name="privacy_policy_file", value=rel
        )
        query = query.on_conflict_do_update(
            index_elements=[params_table.c.user_tg_id, params_table.c.param_name],
            set_={"value": rel},
        )
        await database.execute(query)
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
