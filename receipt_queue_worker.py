"""Сервис последовательной обработки чеков из очереди распознавания.

Инструкция по запуску
----------------------
1. Укажите токен бота либо в переменной окружения ``TELEGRAM_BOT_TOKEN``
   (например, через ``environment=`` в supervisor), либо в файле
   ``new_bot_file/settings.json``. По умолчанию скрипт использует каталог
   ``new_bot_file`` как ``run_directory``.
2. При необходимости задайте путь к ``settings.json`` через переменную
   окружения ``RECEIPT_WORKER_SETTINGS_PATH`` или параметр ``--settings`` —
   это пригодится, если запуск происходит из другого каталога (например,
   аналогично ``new_bot_file/run_bot.py``).
3. Перед первым запуском выполните ``python receipt_queue_worker.py --migrate``
   либо запустите основной бот, чтобы создать/обновить базу данных.
4. Убедитесь, что зависимости установлены (``pip install -r requirements.txt``).
   Для распознавания текста требуется пакет ``easyocr``. При его отсутствии
   воркер сообщит об ошибке в лог, а для резервного распознавания можно
   дополнительно установить ``pytesseract`` и системный бинарник
   ``tesseract-ocr`` (используется как fallback при сбое EasyOCR). По умолчанию
   веса EasyOCR выгружаются после каждого чека, чтобы ограничить рост памяти;
   установите ``OCR_CACHE_READER=1``, если нужно держать модели в памяти.
5. Запустите сервис командой ``python receipt_queue_worker.py`` или через
   упрощённый загрузчик ``run_receipt_worker.py`` в корне проекта (он
   повторяет схему ``run_bot.py`` и автоматически настраивает ``sys.path``).
   Скрипт можно добавить в supervisor как отдельный процесс; при сбое задания
   возвращаются в очередь автоматически.

Скрипт обрабатывает очередь последовательно (по одному чеку) и гарантирует,
что незавершённые задания после падения процесса не теряются и будут
обработаны повторно. Проверка очереди выполняется каждую секунду.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import sql_mgt
from heandlers import media_heandler

IDLE_SLEEP_SECONDS = 1
LOCK_TIMEOUT_SECONDS = 300
RETRY_DELAY_SECONDS = 60
OCR_IDLE_RELEASE_SECONDS = 60
SETTINGS_ENV_VAR = "RECEIPT_WORKER_SETTINGS_PATH"
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


def _collect_memory_usage() -> dict[str, int] | None:
    """Return memory statistics for the current process in bytes."""

    if psutil is not None:  # pragma: no branch - simple guard
        try:
            process = psutil.Process()
            with process.oneshot():
                mem_info = process.memory_info()
            return {"rss": mem_info.rss, "vms": mem_info.vms}
        except Exception:
            logging.exception("Не удалось получить информацию о памяти через psutil")

    try:
        import resource  # type: ignore

        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_bytes = usage.ru_maxrss
        if os.name != "nt":
            rss_bytes *= 1024
        return {"rss": int(rss_bytes)}
    except Exception:
        logging.exception("Не удалось получить информацию о памяти через resource")
    return None


def _format_bytes(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.2f} МБ"


def _log_memory_usage(context: str) -> None:
    stats = _collect_memory_usage()
    if not stats:
        return
    rss = _format_bytes(stats["rss"])
    vms = stats.get("vms")
    if vms is not None:
        logging.info(
            "Использование памяти (%s): RSS=%s, VMS=%s",
            context,
            rss,
            _format_bytes(vms),
        )
    else:
        logging.info("Использование памяти (%s): RSS=%s", context, rss)


def _resolve_settings_path(explicit_path: str | os.PathLike[str] | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    env_path = os.getenv(SETTINGS_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return SETTINGS_PATH


def _load_settings(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        raise FileNotFoundError(f"Не найден файл настроек: {settings_path}")
    with settings_path.open("r", encoding="utf-8") as fh:
        settings = json.load(fh)
    settings["run_directory"] = str(settings_path.parent)
    return settings


def create_context(
    settings_path: str | os.PathLike[str] | Path | None = None,
) -> WorkerContext:
    settings_file = _resolve_settings_path(settings_path)
    settings = _load_settings(settings_file)
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
    last_job_completed_at: float | None = None
    _log_memory_usage("startup")

    while not stop_event.is_set():
        job = await sql_mgt.acquire_next_receipt_for_ocr(
            lock_timeout_seconds=LOCK_TIMEOUT_SECONDS
        )
        if job is None:
            if (
                last_job_completed_at is not None
                and time.monotonic() - last_job_completed_at >= OCR_IDLE_RELEASE_SECONDS
            ):
                media_heandler.release_ocr_resources()
                _log_memory_usage("idle-release")
                last_job_completed_at = None
            if await _wait_with_stop(stop_event, IDLE_SLEEP_SECONDS):
                break
            continue

        queue_id, receipt_id, attempt = job
        _log_memory_usage(f"before receipt_id={receipt_id}")
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
        finally:
            last_job_completed_at = time.monotonic()
            # EasyOCR может удерживать значительные объёмы памяти даже после
            # завершения задачи. Принудительно освобождаем ресурсы после
            # каждого чека, чтобы предотвратить рост потребления памяти.
            media_heandler.release_ocr_resources()
            _log_memory_usage(f"after receipt_id={receipt_id}")
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
        _log_memory_usage("shutdown")
        logging.info("Сервис очереди распознавания остановлен")


def main(settings_path: str | os.PathLike[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Очередь распознавания чеков")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Только применить миграции базы данных и завершиться",
    )
    parser.add_argument(
        "--settings",
        help="Путь к settings.json (по умолчанию определяется автоматически)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    context = create_context(args.settings or settings_path)

    try:
        asyncio.run(run_worker(args.migrate))
    finally:
        if context.ocr_pool:
            context.ocr_pool.shutdown(wait=False)
        media_heandler.release_ocr_resources()
        asyncio.run(_close_bot_session(context.bot))


async def _close_bot_session(bot: Bot) -> None:
    await bot.session.close()


if __name__ == "__main__":
    main()
