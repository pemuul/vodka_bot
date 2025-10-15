"""Helpers for распознавание текста на чеках с помощью EasyOCR."""

from __future__ import annotations

import gc
import logging
import os
import threading
import warnings
from pathlib import Path
from typing import Iterable, Tuple

warnings.filterwarnings("ignore", message=".*pin_memory.*")

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

logger = logging.getLogger(__name__)

_DEFAULT_LANGUAGES: Tuple[str, ...] = tuple(
    filter(None, (lang.strip() for lang in os.getenv("OCR_LANGUAGES", "ru,en").split(",")))
) or ("ru", "en")
_FALLBACK_LANG: str = os.getenv("OCR_FALLBACK_LANG", "rus+eng")
_MAX_DIMENSION: int = int(os.getenv("OCR_MAX_DIMENSION", "2048"))

_reader_lock = threading.Lock()
_reader: "easyocr.Reader | None" = None
_reader_languages: Tuple[str, ...] | None = None


class OCRWorkerError(RuntimeError):
    """Исключение при сбое распознавания текста."""


def _ensure_languages(languages: Iterable[str] | None) -> Tuple[str, ...]:
    if languages is None:
        return _DEFAULT_LANGUAGES
    langs = tuple(lang.strip() for lang in languages if lang and lang.strip())
    return langs or _DEFAULT_LANGUAGES


def _load_image(path: Path):
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - зависимость окружения
        raise OCRWorkerError(f"OpenCVImportError: {exc}") from exc

    image = cv2.imread(str(path))
    if image is None:
        raise OCRWorkerError(f"Не удалось прочитать изображение: {path}")

    if _MAX_DIMENSION > 0:
        height, width = image.shape[:2]
        max_dim = max(height, width)
        if max_dim > _MAX_DIMENSION:
            scale = _MAX_DIMENSION / float(max_dim)
            new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
            image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image


def _get_reader(languages: Iterable[str] | None = None):
    global _reader, _reader_languages

    langs = _ensure_languages(languages)
    with _reader_lock:
        if _reader is not None and _reader_languages == langs:
            return _reader

        try:
            import easyocr  # type: ignore
        except Exception as exc:  # pragma: no cover - зависимость окружения
            raise OCRWorkerError(f"EasyOCRImportError: {exc}") from exc

        try:
            reader = easyocr.Reader(list(langs), gpu=False, verbose=False)
        except Exception as exc:  # pragma: no cover - ошибки easyocr/torch
            raise OCRWorkerError(f"EasyOCRError: {exc}") from exc

        _reader = reader
        _reader_languages = langs
        return _reader


def _fallback_with_tesseract(path: Path, reason: str | None = None) -> str | None:
    """Попробовать распознать текст с помощью pytesseract."""

    try:
        import pytesseract  # type: ignore
    except Exception as exc:  # pragma: no cover - не обязательная зависимость
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


def extract_text(image_path: str, timeout: float | None = None) -> str:
    """Распознать текст на изображении ``image_path``."""

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    image = _load_image(path)

    try:
        reader = _get_reader()
    except OCRWorkerError as exc:
        fallback = _fallback_with_tesseract(path, str(exc))
        if fallback is not None:
            return fallback
        raise

    try:
        lines = reader.readtext(image, detail=0, paragraph=True)
    except Exception as exc:  # pragma: no cover - ошибки из native кода
        fallback = _fallback_with_tesseract(path, f"EasyOCRError: {exc}")
        if fallback is not None:
            return fallback
        raise OCRWorkerError(f"EasyOCRError: {exc}") from exc
    finally:
        # EasyOCR держит ссылки на исходные массивы изображений, поэтому
        # явно удаляем их и просим сборщик мусора освободить память.
        del image
        gc.collect()

    text = "\n".join(str(line) for line in lines if line is not None)
    if text.strip():
        return text

    fallback = _fallback_with_tesseract(path, "empty EasyOCR result")
    if fallback is not None:
        return fallback

    return text


def release_reader() -> None:
    """Освободить кэш EasyOCR Reader."""

    global _reader, _reader_languages
    with _reader_lock:
        _reader = None
        _reader_languages = None
