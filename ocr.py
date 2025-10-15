"""Helpers for running EasyOCR in an isolated subprocess to avoid memory leaks."""

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
    filter(None, (lang.strip() for lang in os.getenv("OCR_LANGUAGES", "ru,en").split(",")))
) or ("ru", "en")
_FALLBACK_LANG: str = os.getenv("OCR_FALLBACK_LANG", "rus+eng")
_MAX_DIMENSION: int = int(os.getenv("OCR_MAX_DIMENSION", "1600"))
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_TIMEOUT", "35"))

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


def _format_worker_failure(reason: str, code: int | None, stdout: str | None, stderr: str | None) -> str:
    parts = [f"worker failure: {reason}"]
    if code is not None:
        parts.append(f"exit_code={code}")
    if stdout:
        parts.append(f"stdout={stdout.strip()}")
    if stderr:
        parts.append(f"stderr={stderr.strip()}")
    return "; ".join(parts)


def _spawn_worker(path: Path, timeout: float | None) -> str:
    script = Path(__file__).with_name("ocr_worker_cli.py")
    if not script.exists():
        raise OCRWorkerError("worker script not found")

    languages = _ensure_languages(None)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    cmd = [
        sys.executable,
        str(script),
        "--image",
        str(path),
        "--output",
        str(tmp_path),
        "--languages",
        ",".join(languages),
    ]
    if _MAX_DIMENSION > 0:
        cmd.extend(["--max-dimension", str(_MAX_DIMENSION)])

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise TimeoutError(f"OCR worker timeout after {effective_timeout} секунд") from exc

    stdout = completed.stdout
    stderr = completed.stderr
    tmp_exists = tmp_path.exists()

    try:
        if completed.returncode != 0:
            raise OCRWorkerError(
                _format_worker_failure("non-zero exit", completed.returncode, stdout, stderr)
            )

        if not tmp_exists:
            raise OCRWorkerError(
                _format_worker_failure("missing output", completed.returncode, stdout, stderr)
            )

        data = json.loads(tmp_path.read_text(encoding="utf-8"))
    except OCRWorkerError:
        raise
    except Exception as exc:  # pragma: no cover - JSON/IO ошибки
        raise OCRWorkerError(
            _format_worker_failure(f"invalid output: {exc}", completed.returncode, stdout, stderr)
        ) from exc
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    if not data.get("success"):
        raise OCRWorkerError(
            _format_worker_failure(data.get("error", "unknown"), completed.returncode, stdout, stderr)
        )

    return data.get("text", "")


def extract_text(image_path: str, timeout: float | None = None) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    _log_memory("ocr:before-worker")
    try:
        text = _spawn_worker(path, timeout)
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
    """Compatibility shim for legacy code: subprocess-based worker has no cache."""

    logger.debug("EasyOCR subprocess mode активен — release_reader ничего не делает")
