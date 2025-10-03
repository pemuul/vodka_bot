import json
import os
import sys
from pathlib import Path


def _load_settings(settings_path: Path) -> tuple[dict, str]:
    with settings_path.open("r", encoding="utf-8") as fh:
        settings = json.load(fh)
    version = settings.get("VERSION_BOT")
    if not version:
        raise RuntimeError("В settings.json не указан VERSION_BOT")
    return settings, version


def _setup_paths(base_dir: Path, version: str) -> None:
    target_directory = base_dir / version
    if str(target_directory) not in sys.path:
        sys.path.insert(0, str(target_directory))


def _setup_environment(settings: dict, settings_path: Path) -> None:
    token = settings.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        os.environ.setdefault("TELEGRAM_BOT_TOKEN", token)
    os.environ.setdefault("RECEIPT_WORKER_SETTINGS_PATH", str(settings_path))


def main(settings_path: str | os.PathLike[str] | None = None) -> None:
    base_dir = Path(__file__).resolve().parent
    if settings_path is None:
        settings_file = base_dir / "settings.json"
    else:
        settings_file = Path(settings_path).expanduser().resolve()

    settings, version = _load_settings(settings_file)
    _setup_paths(base_dir, version)
    _setup_environment(settings, settings_file)

    from receipt_queue_worker import main as worker_main  # noqa: WPS433

    settings.setdefault("commands", {})
    settings["run_directory"] = str(base_dir)

    worker_main(str(settings_file))


if __name__ == "__main__":
    main()
