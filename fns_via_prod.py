"""Локальный dev-хелпер: выполнить fns_api.get_receipt_by_qr() НА ПРОДЕ по SSH.

Не часть боевого кода — на проде этот файл не используется и не деплоится.
Нужен, потому что локально нет FNS_MASTER_TOKEN, а копировать прод-токен на
локальную машину не хотим. Вместо этого сам SOAP-запрос к ФНС выполняется на
проде тем же кодом fns_api.py (там уже стоит токен в окружении supervisor),
а сюда возвращается только результат (ticket/error), никогда не сам токен.

Использовать точечно (ручной smoke-test), не как постоянный источник данных
для локального воркера — это реальный прод-токен ФНС с его квотой.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

_SERVER_ACCESS_PATH = Path(__file__).parent / "server_access.md"
_SSH_HOST = "217.198.6.100"
_SSH_USER = "root"

_REMOTE_SCRIPT = r"""
set -e
TOKEN=$(grep -oP 'FNS_MASTER_TOKEN="\K[^"]+' /etc/supervisor/conf.d/vodka_services.conf | head -1)
cd /home/VodkaBot/vodka_bot
FNS_MASTER_TOKEN="$TOKEN" /home/VodkaBot/venv/bin/python3 - <<'PYEOF'
import base64, json, os, sys
sys.path.insert(0, ".")
import fns_api
qr = base64.b64decode(os.environ["QR_B64"]).decode("utf-8")
ticket, error = fns_api.get_receipt_by_qr(qr)
print("__RESULT__" + json.dumps({"ticket": ticket, "error": error}, ensure_ascii=False))
PYEOF
"""


def _read_ssh_password() -> str:
    text = _SERVER_ACCESS_PATH.read_text(encoding="utf-8")
    match = re.search(r"\| Пароль \| (.+?) \|", text)
    if not match:
        raise RuntimeError("Не удалось найти пароль SSH в server_access.md")
    return match.group(1)


_AUTH_FAILURE_MARKERS = ("permission denied", "please try again")

# sshpass не понимает протокол SSH — он просто ловит текст приглашения пароля по паттерну
# и иногда промахивается мимо тайминга на медленном отклике сервера (тот же пароль штатно
# срабатывает секундами раньше/позже). Живой случай: сервер отклонил пароль с этой же
# машины в 21:41:46, а уже в 21:43:08 (тем же паролем) вход прошёл — подтверждено логом
# auth сервера, не смена пароля и не блокировка (fail2ban на сервере не установлен).
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 3


def _looks_like_transient_auth_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)


def _run_ssh_once(password: str, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "sshpass",
            "-p",
            password,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "PreferredAuthentications=password",
            f"{_SSH_USER}@{_SSH_HOST}",
            remote_cmd,
        ],
        input=_REMOTE_SCRIPT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_receipt_by_qr_via_prod(qr: str, timeout: int = 40) -> Tuple[Optional[dict], Optional[str]]:
    """Как fns_api.get_receipt_by_qr(), но SOAP-запрос выполняется на проде."""

    password = _read_ssh_password()
    qr_b64 = base64.b64encode(qr.encode("utf-8")).decode("ascii")
    remote_cmd = f"QR_B64='{qr_b64}' bash -s"

    result = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result = _run_ssh_once(password, remote_cmd, timeout)
        if result.returncode == 0:
            break
        if attempt < _MAX_ATTEMPTS and _looks_like_transient_auth_failure(result.stderr):
            time.sleep(_RETRY_DELAY_SECONDS)
            continue
        raise RuntimeError(f"SSH-релей на прод упал: {result.stderr.strip()}")

    result_line = next(
        (line for line in result.stdout.splitlines() if line.startswith("__RESULT__")),
        None,
    )
    if result_line is None:
        raise RuntimeError(f"Не нашли результат в выводе прода: {result.stdout!r} / {result.stderr!r}")

    data = json.loads(result_line[len("__RESULT__"):])
    return data["ticket"], data["error"]


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Использование: python3 fns_via_prod.py '<QR-строка>'")
        raise SystemExit(1)

    ticket, error = get_receipt_by_qr_via_prod(sys.argv[1])
    print(json.dumps({"ticket": ticket, "error": error}, ensure_ascii=False, indent=2))
