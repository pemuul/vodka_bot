"""Run EasyOCR via a short-lived helper process to avoid memory leaks."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Tuple

logger = logging.getLogger(__name__)

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

_DEFAULT_LANGUAGES: Tuple[str, ...] = tuple(
    filter(None, (lang.strip() for lang in os.getenv("OCR_LANGUAGES", "ru").split(",")))
) or ("ru",)
_FALLBACK_LANG: str = os.getenv("OCR_FALLBACK_LANG", "rus+eng")
_MAX_DIMENSION: int = int(os.getenv("OCR_MAX_DIMENSION", "1600"))
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_TIMEOUT", "35"))
_RECOG_NETWORK: str | None = os.getenv("OCR_RECOG_NETWORK") or None

try:  # pragma: no cover - psutil не обязателен в окружении тестов
    import psutil  # type: ignore

    _PROCESS = psutil.Process()
except Exception:  # pragma: no cover
    _PROCESS = None


class OCRWorkerError(RuntimeError):
    """Raised when the EasyOCR helper process fails."""


def _log_memory(label: str) -> None:
    if _PROCESS is None:
        return
    try:
        mem = _PROCESS.memory_info().rss / (1024 * 1024)
    except Exception:  # pragma: no cover - защитная проверка
        return
    logger.info("Использование памяти (%s): RSS=%.2f МБ", label, mem)


def _ensure_languages(languages: Iterable[str] | None) -> Tuple[str, ...]:
    if languages is None:
        return _DEFAULT_LANGUAGES
    langs = tuple(lang.strip() for lang in languages if lang and lang.strip())
    return langs or _DEFAULT_LANGUAGES


def _fallback_with_tesseract(path: Path, reason: str | None = None) -> str | None:
    """Попробовать распознать текст с помощью pytesseract."""

    try:
        import pytesseract  # type: ignore
    except Exception as exc:  # pragma: no cover - pytesseract опционален
        logger.warning(
            "EasyOCR failed (%s) и pytesseract недоступен: %s",
            reason or "unknown",
            exc,
        )
        return None

    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "EasyOCR failed (%s) и OpenCV недоступен для fallback: %s",
            reason or "unknown",
            exc,
        )
        return None

    image = cv2.imread(str(path))
    if image is None:
        logger.warning(
            "EasyOCR failed (%s); fallback не смог прочитать %s",
            reason or "unknown",
            path,
        )
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    try:
        text = pytesseract.image_to_string(gray, lang=_FALLBACK_LANG)
    except pytesseract.pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR failed (%s) и бинарник tesseract не найден: %s",
            reason or "unknown",
            exc,
        )
        return None
    except pytesseract.pytesseract.TesseractError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR failed (%s); pytesseract вернул ошибку: %s",
            reason or "unknown",
            exc,
        )
        return None
    except Exception as exc:  # pragma: no cover - защита от нестандартных ошибок
        logger.warning(
            "EasyOCR failed (%s); непредвиденная ошибка pytesseract: %s",
            reason or "unknown",
            exc,
        )
        return None

    logger.info(
        "EasyOCR failed (%s); успешно использован pytesseract fallback для %s",
        reason or "unknown",
        path,
    )
    return text


def _run_easyocr_subprocess(path: Path, timeout: float | None) -> str:
    """Запустить EasyOCR в отдельном процессе и вернуть распознанный текст."""

    script_path = Path(__file__).with_name("ocr_worker_cli.py")
    if not script_path.exists():
        raise OCRWorkerError("Не найден ocr_worker_cli.py")

    languages = ",".join(_ensure_languages(None))

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        output_path = Path(tmp.name)

    cmd = [
        sys.executable,
        str(script_path),
        "--image",
        str(path),
        "--output",
        str(output_path),
        "--languages",
        languages,
        "--max-dimension",
        str(_MAX_DIMENSION),
    ]
    if _RECOG_NETWORK:
        cmd.extend(["--recog-network", _RECOG_NETWORK])

    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise TimeoutError(f"OCR worker timeout after {effective_timeout} секунд") from exc

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OCRWorkerError("worker produced no output") from exc
    except json.JSONDecodeError as exc:
        output_path.unlink(missing_ok=True)
        raise OCRWorkerError("invalid worker response") from exc
    finally:
        output_path.unlink(missing_ok=True)

    if completed.returncode != 0 and not payload.get("error"):
        raise OCRWorkerError(
            f"worker failure: non-zero exit; exit_code={completed.returncode}; stderr={stderr}"
        )

    if not payload.get("success"):
        error = payload.get("error", "unknown")
        logger.warning(
            "EasyOCR subprocess failed: %s (stdout=%s, stderr=%s)", error, stdout, stderr
        )
        raise OCRWorkerError(error)

    text = payload.get("text", "")
    if not isinstance(text, str):
        raise OCRWorkerError("worker returned non-string text")

    return text


def extract_text(image_path: str, timeout: float | None = None) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    _log_memory("ocr:before-worker")
    try:
        text = _run_easyocr_subprocess(path, timeout)
    except TimeoutError:
        raise
    except OCRWorkerError as exc:
        fallback = _fallback_with_tesseract(path, str(exc))
        if fallback is not None:
            return fallback
        raise
    finally:
        _log_memory("ocr:after-worker")

    if text.strip():
        return text

    fallback = _fallback_with_tesseract(path, "empty EasyOCR result")
    if fallback is not None:
        return fallback

    return text


def release_reader() -> None:
    """Совместимость: фонового воркера нет, освобождать нечего."""

    logger.debug("release_reader() вызван, но постоянный OCR процесс не используется")
