import json
import sys
from pathlib import Path


CURRENT_DIRECTORY = Path(__file__).resolve().parent
SETTINGS_PATH = CURRENT_DIRECTORY / "settings.json"

with SETTINGS_PATH.open("r", encoding="utf-8") as fh:
    settings_bot = json.load(fh)
    version_bot = settings_bot["VERSION_BOT"]

target_directory = CURRENT_DIRECTORY / version_bot
sys.path.insert(0, str(target_directory))

settings_bot["run_directory"] = str(CURRENT_DIRECTORY)

from bot import run_bot  # noqa: E402


if __name__ == "__main__":
    run_bot(
        settings_bot["TELEGRAM_BOT_TOKEN"],
        settings_bot.get("ADMIN_ID_LIST", []),
        settings_bot.get("commands", {}),
        settings_bot,
    )
