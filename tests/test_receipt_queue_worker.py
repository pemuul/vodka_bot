"""Tests for receipt_queue_worker.py — settings loading and WorkerContext."""

import json
import os
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_queue_worker import (
    _resolve_settings_path,
    _load_settings,
    SETTINGS_ENV_VAR,
    SETTINGS_PATH,
)


# ---------------------------------------------------------------------------
# _resolve_settings_path
# ---------------------------------------------------------------------------

class TestResolveSettingsPath:
    def test_explicit_path_takes_priority(self, tmp_path):
        explicit = tmp_path / "my_settings.json"
        explicit.write_text("{}", encoding="utf-8")
        result = _resolve_settings_path(str(explicit))
        assert result == explicit.resolve()

    def test_env_var_used_when_no_explicit(self, tmp_path, monkeypatch):
        env_path = tmp_path / "env_settings.json"
        env_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv(SETTINGS_ENV_VAR, str(env_path))
        result = _resolve_settings_path(None)
        assert result == env_path.resolve()

    def test_default_path_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv(SETTINGS_ENV_VAR, raising=False)
        result = _resolve_settings_path(None)
        assert result == SETTINGS_PATH


# ---------------------------------------------------------------------------
# _load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_loads_valid_json(self, tmp_path):
        settings = {"TELEGRAM_BOT_TOKEN": "tok123", "VERSION_BOT": "v_2"}
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(settings), encoding="utf-8")
        loaded = _load_settings(path)
        assert loaded["TELEGRAM_BOT_TOKEN"] == "tok123"

    def test_injects_run_directory(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{}", encoding="utf-8")
        loaded = _load_settings(path)
        assert "run_directory" in loaded
        assert loaded["run_directory"] == str(tmp_path)

    def test_raises_when_file_missing(self, tmp_path):
        missing = tmp_path / "no_file.json"
        with pytest.raises(FileNotFoundError):
            _load_settings(missing)

    def test_nested_settings_preserved(self, tmp_path):
        settings = {
            "bot_settings": {"restart": {"hour": 3, "minet": 30}},
            "site": {"site_on": False}
        }
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(settings), encoding="utf-8")
        loaded = _load_settings(path)
        assert loaded["bot_settings"]["restart"]["hour"] == 3
        assert loaded["site"]["site_on"] is False
