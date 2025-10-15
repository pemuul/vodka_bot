"""OCR helper that runs EasyOCR in an isolated subprocess.

The EasyOCR models are quite heavy and tend to increase the memory usage of the
current process every time they are loaded. To keep the main bot and receipt
worker lightweight we execute the recognition inside a short-lived helper
process that is terminated after the text is extracted. This ensures all
allocations are reclaimed by the operating system once the child exits.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

_DEFAULT_LANGUAGES: tuple[str, ...] = ("ru", "en")
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_WORKER_TIMEOUT", "25"))
_FALLBACK_LANG: str = os.getenv("OCR_FALLBACK_LANG", "rus+eng")

logger = logging.getLogger(__name__)


class OCRWorkerError(RuntimeError):
    """Raised when the OCR worker fails to return a successful result."""


def _summarize_failure(returncode: int, stdout: str, stderr: str) -> str:
    """Compose a human readable failure message from worker outputs."""

    details: list[str] = []
    if returncode:
        details.append(f"exit code {returncode}")
    if stdout:
        details.append(f"stdout: {stdout.strip()}")
    if stderr:
        details.append(f"stderr: {stderr.strip()}")
    return "; ".join(details) or "worker terminated without diagnostics"


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

    cmd: list[str] = [
        sys.executable,
        "-u",
        str(worker_path),
        "--image",
        image_path,
        "--output",
        str(output_file),
    ]
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
    summary = _summarize_failure(completed.returncode, stdout, stderr)

    if output_file is None or not output_file.exists():
        raise OCRWorkerError(f"worker produced no output ({summary})")

    raw_payload = output_file.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise OCRWorkerError(f"invalid worker response ({summary})") from exc
    finally:
        if output_file is not None:
            output_file.unlink(missing_ok=True)

    if not raw_payload.strip():
        raise OCRWorkerError(f"worker returned empty payload ({summary})")

    if not payload:
        raise OCRWorkerError("worker returned empty payload")

    success = bool(payload.get("success"))
    message = payload.get("text") if success else payload.get("error", "unknown error")
    return success, message or ""


def _fallback_with_tesseract(path: Path, reason: str | None = None) -> str | None:
    """Attempt to extract text with pytesseract if EasyOCR is unavailable."""

    try:
        import pytesseract  # type: ignore
    except Exception as exc:  # pragma: no cover - environment specific
        logger.warning(
            "EasyOCR worker failed (%s) and pytesseract is not available: %s",
            reason or "unknown reason",
            exc,
        )
        return None

    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - OpenCV should be present
        logger.warning(
            "EasyOCR worker failed (%s) and OpenCV is unavailable for fallback: %s",
            reason or "unknown reason",
            exc,
        )
        return None

    image = cv2.imread(str(path))
    if image is None:
        logger.warning(
            "EasyOCR worker failed (%s) and fallback image load failed for %s",
            reason or "unknown reason",
            path,
        )
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    try:
        text = pytesseract.image_to_string(gray, lang=_FALLBACK_LANG)
    except pytesseract.pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR worker failed (%s) and Tesseract binary is missing: %s",
            reason or "unknown reason",
            exc,
        )
        return None
    except pytesseract.pytesseract.TesseractError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR worker failed (%s); pytesseract returned an error: %s",
            reason or "unknown reason",
            exc,
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "EasyOCR worker failed (%s); unexpected pytesseract error: %s",
            reason or "unknown reason",
            exc,
        )
        return None

    logger.info(
        "EasyOCR worker failed (%s); successfully used pytesseract fallback for %s",
        reason or "unknown reason",
        path,
    )
    return text


def extract_text(image_path: str, timeout: float | None = None) -> str:
    """Extract text from *image_path* using EasyOCR inside an isolated worker."""

    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    try:
        success, payload = _spawn_worker(str(path), timeout)
    except TimeoutError:
        fallback_text = _fallback_with_tesseract(path, "timeout")
        if fallback_text is not None:
            return fallback_text
        raise
    except OCRWorkerError as exc:
        fallback_text = _fallback_with_tesseract(path, str(exc))
        if fallback_text is not None:
            return fallback_text
        raise

    if success:
        return payload

    fallback_text = _fallback_with_tesseract(path, payload)
    if fallback_text is not None:
        return fallback_text

    raise OCRWorkerError(payload)


def release_reader() -> None:  # pragma: no cover - kept for backward compat
    """No-op placeholder kept for compatibility with previous interface."""

    return None
