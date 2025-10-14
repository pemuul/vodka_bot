"""OCR helper that runs EasyOCR in an isolated subprocess.

The EasyOCR models are quite heavy and tend to increase the memory usage of the
current process every time they are loaded. To keep the main bot and receipt
worker lightweight we execute the recognition inside a short-lived helper
process that is terminated after the text is extracted. This ensures all
allocations are reclaimed by the operating system once the child exits.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

_DEFAULT_LANGUAGES: tuple[str, ...] = ("ru", "en")
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_WORKER_TIMEOUT", "25"))


class OCRWorkerError(RuntimeError):
    """Raised when the OCR worker fails to return a successful result."""


def _spawn_worker(image_path: str, timeout: float) -> tuple[bool, str]:
    """Execute the helper script that performs OCR inside a clean process."""

    worker_path = Path(__file__).with_name("ocr_worker_cli.py")
    if not worker_path.exists():  # pragma: no cover - deployment guard
        raise OCRWorkerError("worker helper script not found")

    output_file: Path | None = None
    tmp_handle = None
    try:
        tmp_handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
        output_file = Path(tmp_handle.name)
        tmp_handle.close()
    except OSError as exc:  # pragma: no cover - filesystem safety
        raise OCRWorkerError(f"failed to prepare worker output file: {exc}") from exc

    cmd: list[str] = [sys.executable, "-u", str(worker_path), "--image", image_path, "--output", str(output_file)]
    for lang in _DEFAULT_LANGUAGES:
        cmd.extend(["--lang", lang])

    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        if output_file is not None:
            output_file.unlink(missing_ok=True)
        raise TimeoutError(f"timeout after {timeout} seconds") from exc

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if output_file is None or not output_file.exists():
        message = stderr or stdout or f"exit code {completed.returncode}"
        raise OCRWorkerError(f"worker produced no output: {message}")

    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise OCRWorkerError("invalid worker response") from exc
    finally:
        if output_file is not None:
            output_file.unlink(missing_ok=True)

    if not payload:
        raise OCRWorkerError("worker returned empty payload")

    success = bool(payload.get("success"))
    message = payload.get("text") if success else payload.get("error", "unknown error")
    return success, message or ""


def extract_text(image_path: str, timeout: float | None = None) -> str:
    """Extract text from *image_path* using EasyOCR inside an isolated worker."""

    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    success, payload = _spawn_worker(str(path), timeout)
    if not success:
        raise OCRWorkerError(payload)
    return payload


def release_reader() -> None:  # pragma: no cover - kept for backward compat
    """No-op placeholder kept for compatibility with previous interface."""

    return None
