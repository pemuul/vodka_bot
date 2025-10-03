"""Запускатель очереди чеков, аналогичный ``run_bot.py``.

Скрипт поднимает нужные пути ``sys.path`` в зависимости от расположения файла
и значения ``VERSION_BOT`` в ``settings.json``. Благодаря этому его можно
поместить в ту же директорию, что и основной ``run_bot.py``, и он по-прежнему
найдёт проект даже при запуске из другого каталога (например, Supervisor).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterable

CURRENT_DIRECTORY = Path(__file__).resolve().parent
SETTINGS_PATH = CURRENT_DIRECTORY / "settings.json"

if not SETTINGS_PATH.exists():
    raise FileNotFoundError(f"Не найден settings.json рядом со скриптом: {SETTINGS_PATH}")

with SETTINGS_PATH.open("r", encoding="utf-8") as fh:
    settings_bot = json.load(fh)
    version_bot = settings_bot.get("VERSION_BOT")


def _candidate_roots(base: Path, version: str | None) -> Iterable[Path]:
    if version:
        yield (base / version).resolve()
        yield (base.parent / version).resolve()
        yield (base.parent.parent / version).resolve()
    yield base.resolve()
    yield base.parent.resolve()


def _resolve_project_root() -> Path:
    for candidate in _candidate_roots(CURRENT_DIRECTORY, version_bot):
        worker_path = candidate / "receipt_queue_worker.py"
        if worker_path.exists():
            return candidate
    raise RuntimeError(
        "Не удалось найти файл receipt_queue_worker.py рядом с run_receipt_worker.py. "
        "Проверьте значение VERSION_BOT в settings.json и расположение скриптов."
    )


project_root = _resolve_project_root()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", settings_bot.get("TELEGRAM_BOT_TOKEN", ""))
os.environ.setdefault("RECEIPT_WORKER_SETTINGS_PATH", str(SETTINGS_PATH))

from receipt_queue_worker import main  # noqa: E402  pylint: disable=wrong-import-position


if __name__ == "__main__":
    main(str(SETTINGS_PATH))
