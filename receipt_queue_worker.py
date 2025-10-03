"""Сервис последовательной обработки чеков из очереди распознавания.

Инструкция по запуску
----------------------
1. Укажите токен бота либо в переменной окружения ``TELEGRAM_BOT_TOKEN``
   (например, через ``environment=`` в supervisor), либо в файле
   ``new_bot_file/settings.json``. По умолчанию скрипт использует каталог
   ``new_bot_file`` как ``run_directory``.
2. Перед первым запуском выполните ``python receipt_queue_worker.py --migrate``
   либо запустите основной бот, чтобы создать/обновить базу данных.
3. Запустите сервис командой ``python receipt_queue_worker.py`` в том же
   окружении, что и основной бот. Скрипт можно добавить в supervisor как
   отдельный процесс; при сбое задания возвращаются в очередь автоматически.

Скрипт обрабатывает очередь последовательно (по одному чеку) и гарантирует,
что незавершённые задания после падения процесса не теряются и будут
обработаны повторно. Проверка очереди выполняется каждые 3 секунды.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import sql_mgt
from heandlers import media_heandler

IDLE_SLEEP_SECONDS = 3
LOCK_TIMEOUT_SECONDS = 300
RETRY_DELAY_SECONDS = 60
SETTINGS_PATH = Path(__file__).resolve().parent / "new_bot_file" / "settings.json"


@dataclass
class WorkerContext:
    bot: Bot
    settings_bot: dict[str, Any]
    admin_list: list[int] = field(default_factory=list)
    command_dict: dict[str, Any] = field(default_factory=dict)
    dp: Any | None = None
    tree_data: Any | None = None
    ocr_pool: concurrent.futures.Executor | None = None


def _load_settings(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        raise FileNotFoundError(f"Не найден файл настроек: {settings_path}")
    with settings_path.open("r", encoding="utf-8") as fh:
        settings = json.load(fh)
    settings["run_directory"] = str(settings_path.parent)
    return settings


def create_context(settings_path: Path = SETTINGS_PATH) -> WorkerContext:
    settings = _load_settings(settings_path)
    token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Не удалось получить TELEGRAM_BOT_TOKEN из переменной окружения или settings.json"
        )

    settings["TELEGRAM_BOT_TOKEN"] = token

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    admin_ids = settings.get("ADMIN_ID_LIST")
    if isinstance(admin_ids, list):
        admin_list = [int(x) for x in admin_ids]
    else:
        admin_list = []

    context = WorkerContext(
        bot=bot,
        settings_bot=settings,
        admin_list=admin_list,
        ocr_pool=pool,
    )
    sql_mgt.init_object(context)
    sql_mgt.create_db_file()
    media_heandler.global_objects = context
    return context


async def _migrate_database() -> None:
    await sql_mgt.create_db()


async def _wait_with_stop(stop_event: asyncio.Event, timeout: float) -> bool:
    """Wait for ``timeout`` seconds or until the stop event is set.

    Returns ``True`` if the stop event was set, ``False`` if the timeout expired.
    """

    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    return True


async def _process_queue(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        job = await sql_mgt.acquire_next_receipt_for_ocr(
            lock_timeout_seconds=LOCK_TIMEOUT_SECONDS
        )
        if job is None:
            if await _wait_with_stop(stop_event, IDLE_SLEEP_SECONDS):
                break
            continue

        queue_id, receipt_id, attempt = job
        logging.info(
            "Получена задача распознавания: queue_id=%s receipt_id=%s attempt=%s",
            queue_id,
            receipt_id,
            attempt,
        )
        try:
            receipt = await sql_mgt.get_receipt(receipt_id)
            if not receipt:
                logging.warning(
                    "Чек %s не найден в базе — помечаем задачу завершённой", receipt_id
                )
                await sql_mgt.mark_receipt_queue_complete(queue_id)
                continue

            file_path: Optional[str] = receipt.get("file_path")
            if not file_path:
                raise RuntimeError("у записи чека отсутствует путь к файлу")

            dest_path = media_heandler.UPLOAD_DIR_CHECKS / Path(file_path).name
            chat_id = receipt.get("user_tg_id")
            message_id = receipt.get("message_id")

            if chat_id is None:
                raise RuntimeError("не указан идентификатор чата пользователя")

            await media_heandler.process_receipt(dest_path, chat_id, message_id, receipt_id)
            await sql_mgt.mark_receipt_queue_complete(queue_id)
            logging.info("Чек %s успешно обработан", receipt_id)
        except Exception as exc:  # noqa: BLE001
            logging.exception("Ошибка обработки чека %s", receipt_id)
            await sql_mgt.mark_receipt_queue_failed(
                queue_id,
                str(exc),
                retry_delay_seconds=RETRY_DELAY_SECONDS,
            )
        if await _wait_with_stop(stop_event, IDLE_SLEEP_SECONDS):
            break


async def run_worker(migrate_only: bool) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        if not stop_event.is_set():
            logging.info("Получен сигнал завершения, останавливаемся после текущей задачи")
            stop_event.set()

    registered_signals: list[int] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
            registered_signals.append(sig)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _request_stop())

    try:
        if migrate_only:
            await _migrate_database()
            logging.info("Миграция базы данных завершена")
            return

        await _migrate_database()
        logging.info("Сервис очереди распознавания запущен")
        await _process_queue(stop_event)
    finally:
        for sig in registered_signals:
            loop.remove_signal_handler(sig)
        logging.info("Сервис очереди распознавания остановлен")


def main() -> None:
    parser = argparse.ArgumentParser(description="Очередь распознавания чеков")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Только применить миграции базы данных и завершиться",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    context = create_context()

    try:
        asyncio.run(run_worker(args.migrate))
    finally:
        if context.ocr_pool:
            context.ocr_pool.shutdown(wait=False)
        asyncio.run(_close_bot_session(context.bot))


async def _close_bot_session(bot: Bot) -> None:
    await bot.session.close()


if __name__ == "__main__":
    main()
