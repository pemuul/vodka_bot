import json
import os
import sys
from pathlib import Path


CURRENT_DIRECTORY = Path(__file__).resolve().parent
SETTINGS_PATH = CURRENT_DIRECTORY / "settings.json"

with SETTINGS_PATH.open("r", encoding="utf-8") as fh:
    settings_bot = json.load(fh)
    version_bot = settings_bot["VERSION_BOT"]

target_directory = CURRENT_DIRECTORY / version_bot
sys.path.insert(0, str(target_directory))

project_root = CURRENT_DIRECTORY.parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", settings_bot.get("TELEGRAM_BOT_TOKEN", ""))
os.environ.setdefault("RECEIPT_WORKER_SETTINGS_PATH", str(SETTINGS_PATH))

from receipt_queue_worker import main  # noqa: E402


if __name__ == "__main__":
    main(str(SETTINGS_PATH))
