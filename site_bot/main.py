# main.py

from fastapi import FastAPI, Request, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import sessionmaker
from typing import List, Optional, Dict
import datetime
from pydantic import BaseModel

# Админ-панель через SQLAdmin
from sqladmin import Admin, ModelView
import json
import os
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.enums import ParseMode

# ==============================
# Настройка БД
# ==============================
DATABASE_URL = "sqlite:///../../tg_base.sqlite"

database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()

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
receipts_table             = Table("receipts", metadata, autoload_with=engine)
images_table               = Table("images", metadata, autoload_with=engine)
deleted_images_table       = Table("deleted_images", metadata, autoload_with=engine)
notifications_table        = Table("notifications", metadata, autoload_with=engine)

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
    draws_rows = await database.fetch_all(prize_draws_table.select())
    draws = []
    for d in draws_rows:
        stages = []
        stages_rows = await database.fetch_all(
            prize_draw_stages_table.select().where(
                prize_draw_stages_table.c.draw_id == d["id"]
            )
        )
        for idx, s in enumerate(stages_rows):
            winners_rows = await database.fetch_all(
                prize_draw_winners_table.select().where(
                    prize_draw_winners_table.c.stage_id == s["id"]
                )
            )
            winners = [w["winner_name"] for w in winners_rows]
            stages.append({
                "__id": f"stage-{s['id']}",
                "name": s["name"],
                "description": s["description"],
                "winnersCount": s["winners_count"],
                "textBefore": s["text_before"],
                "textAfter": s["text_after"],
                "winners": winners
            })
        draws.append({
            "id": d["id"],
            "title": d["title"],
            "start": d["start_date"].isoformat(),
            "end": d["end_date"].isoformat(),
            "status": d["status"],
            "stages": stages
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
    winners: List[str] = []

class DrawIn(BaseModel):
    id: Optional[int] = None
    title: str
    start: datetime.date
    end: datetime.date
    status: str
    stages: List[StageIn]

@app.post("/prize-draws")
async def save_draw(draw: DrawIn):
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
            await database.execute(
                prize_draw_winners_table.insert().values(
                    stage_id=stage_id,
                    winner_name=winner
                )
            )

    return {"success": True, "id": new_id}

@app.get("/questions", response_class=HTMLResponse)
async def questions(request: Request):
    rows = await database.fetch_all(
        questions_table.select().order_by(questions_table.c.create_dt.desc())
    )
    user_ids = {r["user_tg_id"] for r in rows}
    user_map = {}
    if user_ids:
        user_rows = await database.fetch_all(
            users_table.select().where(users_table.c.tg_id.in_(user_ids))
        )
        user_map = {u["tg_id"]: u["name"] for u in user_rows}

    questions = []
    for q in rows:
        questions.append({
            "id": q["id"],
            "text": q["text"],
            "type": q["type"],
            "status": q["status"],
            "user": {
                "id": q["user_tg_id"],
                "name": user_map.get(q["user_tg_id"], f"Пользователь {q['user_tg_id']}")
            }
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
    user_ids = {r["user_tg_id"] for r in rows}
    user_map = {}
    if user_ids:
        user_rows = await database.fetch_all(
            users_table.select().where(users_table.c.tg_id.in_(user_ids))
        )
        user_map = {u["tg_id"]: u["name"] for u in user_rows}

    questions = []
    for q in rows:
        questions.append({
            "id": q["id"],
            "text": q["text"],
            "type": q["type"],
            "status": q["status"],
            "user": {
                "id": q["user_tg_id"],
                "name": user_map.get(q["user_tg_id"], f"Пользователь {q['user_tg_id']}")
            }
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
                if local.exists():
                    obj = FSInputFile(local)
                else:
                    obj = fname
                files.append((typ, obj))

            if not files:
                if msg["content"]:
                    await bot.send_message(uid, msg["content"])
            elif len(files) == 1:
                typ, fobj = files[0]
                if typ == "photo":
                    await bot.send_photo(uid, fobj, caption=msg["content"] or None)
                else:
                    await bot.send_video(uid, fobj, caption=msg["content"] or None)
            else:
                media_group = []
                for i, (typ, fobj) in enumerate(files):
                    caption = msg["content"] if i == 0 else None
                    if typ == "photo":
                        media_group.append(InputMediaPhoto(media=fobj, caption=caption))
                    else:
                        media_group.append(InputMediaVideo(media=fobj, caption=caption))
                await bot.send_media_group(uid, media_group)
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
                if local.exists():
                    obj = FSInputFile(local)
                else:
                    obj = fname
                files.append((typ, obj))

            if not files:
                if msg["content"]:
                    await bot.send_message(uid, msg["content"])
            elif len(files) == 1:
                typ, fobj = files[0]
                if typ == "photo":
                    await bot.send_photo(uid, fobj, caption=msg["content"] or None)
                else:
                    await bot.send_video(uid, fobj, caption=msg["content"] or None)
            else:
                media_group = []
                for i, (typ, fobj) in enumerate(files):
                    caption = msg["content"] if i == 0 else None
                    if typ == "photo":
                        media_group.append(InputMediaPhoto(media=fobj, caption=caption))
                    else:
                        media_group.append(InputMediaVideo(media=fobj, caption=caption))
                await bot.send_media_group(uid, media_group)
        except Exception as e:
            print("send mailing error", e)

    now = datetime.datetime.utcnow()
    await database.execute(
        scheduled_messages_table.update()
        .where(scheduled_messages_table.c.id == message_id)
        .values(schedule_dt=now, status="Отправлено")
    )
    return {"success": True}

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

@app.get("/receipts", response_class=HTMLResponse)
async def receipts(request: Request):
    rows = await database.fetch_all(
        receipts_table.select().order_by(receipts_table.c.id.desc())
    )
    receipts = []
    for r in rows:
        receipts.append({
            "id": r["id"],
            "number": r["number"],
            "date": r["date"].isoformat(),
            "amount": r["amount"],
            "user_tg_id": r["user_tg_id"],
            "file_path": r["file_path"]
        })
    return templates.TemplateResponse(
        "receipts.html",
        {"request": request, "active_page": "receipts", "receipts_data": receipts, "version": app.state.static_version}
    )

@app.get("/api/receipts/{receipt_id}")
async def get_receipt(receipt_id: int):
    r = await database.fetch_one(
        receipts_table.select().where(receipts_table.c.id == receipt_id)
    )
    if not r:
        raise HTTPException(404, "Receipt not found")
    return {
        "id": r["id"],
        "number": r["number"],
        "date": r["date"].isoformat(),
        "amount": r["amount"],
        "user_tg_id": r["user_tg_id"],
        "file_path": r["file_path"]
    }

@app.delete("/api/receipts/{receipt_id}")
async def delete_receipt(receipt_id: int):
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

telegram_bot_token = '7349498734:AAHJb2K6KuLCMqLpkh3Fo_hFJhtV1WkN8tc' # !!!! надо поменять на глобальную 
bot: Bot = Bot(telegram_bot_token, parse_mode=ParseMode.HTML) 


@app.get("/api/file/{file_id}")
async def proxy_file(file_id: str):
    """
    Перенаправляем клиент на URL файла в Telegram CDN.
    """
    # Получаем метаданные файла у Telegram
    if not file_id or file_id == "undefined":
        raise HTTPException(status_code=400, detail="File ID is required")
    
    file = await bot.get_file(file_id)
    # В file.file_path лежит, например, "photos/file_123.jpg"
    file_path = file.file_path

    # Собираем ссылку на CDN:
    url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"

    # Перенаправляем браузер на этот URL
    return RedirectResponse(url)


class SendMessageIn(BaseModel):
    text: str

@app.post("/api/participants/{user_tg_id}/messages")
async def api_send_message(user_tg_id: int, msg_in: SendMessageIn):
    # 1) отправляем сообщение через бота
    try:
        sent = await bot.send_message(chat_id=user_tg_id, text=msg_in.text)
    except Exception as e:
        raise HTTPException(500, f"Telegram error: {e}")

    # 2) логируем в БД
    values = {
        "user_tg_id": user_tg_id,
        "sender": "admin",
        "text": msg_in.text,
        "buttons": None,
        "media": None,
    }
    if HAS_PM_IS_ANSWER:
        values["is_answer"] = False
    new_id = await database.execute(
        participant_messages_table.insert().values(**values)
    )
    # 3) возвращаем id и timestamp
    return {
        "success": True,
        "id": new_id,
        "text": msg_in.text,
        "timestamp": sent.date.isoformat()
    }


class AnswerIn(BaseModel):
    text: str


@app.post("/api/questions/{question_id}/answer")
async def answer_question(question_id: int, ans: AnswerIn):
    q = await database.fetch_one(
        questions_table.select().where(questions_table.c.id == question_id)
    )
    if not q:
        raise HTTPException(404, "Question not found")

    try:
        sent = await bot.send_message(chat_id=q["user_tg_id"], text=ans.text)
    except Exception as e:
        raise HTTPException(500, f"Telegram error: {e}")

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

    pm_values = {
        "user_tg_id": q["user_tg_id"],
        "sender": "admin",
        "text": ans.text,
        "buttons": None,
        "media": None,
    }
    if HAS_PM_IS_ANSWER:
        pm_values["is_answer"] = True
    await database.execute(
        participant_messages_table.insert().values(**pm_values)
    )
    await database.execute(
        questions_table.update()
        .where(questions_table.c.id == question_id)
        .values(status="Отвечено")
    )

    return {
        "success": True,
        "timestamp": sent.date.isoformat(),
        "is_answer": True
    }
