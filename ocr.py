"""EasyOCR helper that keeps the reader in-process for quick reuse."""

from __future__ import annotations

import gc
import logging
import os
import ctypes
from pathlib import Path
from typing import Iterable, Sequence

import cv2  # type: ignore
import easyocr  # type: ignore
import numpy as np  # type: ignore
import warnings

warnings.filterwarnings("ignore", message=".*pin_memory.*")

__all__ = ["extract_text", "release_reader"]

logger = logging.getLogger(__name__)

# Уменьшаем параллелизм в используемых библиотеках, чтобы снизить число арен glibc
try:  # pragma: no cover - зависит от версии OpenCV
    cv2.setNumThreads(1)
except Exception:
    pass
try:  # pragma: no cover - torch может отсутствовать в окружении
    import torch  # type: ignore

    torch.set_num_threads(int(os.getenv("TORCH_NUM_THREADS", "1")))
except Exception:
    pass


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Некорректное значение для %s: %s", name, raw)
        return default


_DEFAULT_LANGUAGES: Sequence[str] = tuple(
    filter(None, (lang.strip() for lang in os.getenv("OCR_LANGUAGES", "ru").split(",")))
) or ("ru",)
_DEFAULT_RECOG_NETWORK = os.getenv("OCR_RECOG_NETWORK", "cyrillic_g2") or "cyrillic_g2"
_USE_QUANTIZE = _env_flag("OCR_QUANTIZE", default=True)
_MAX_IMAGE_DIM = _env_int("OCR_MAX_IMAGE_DIM", default=1600)

_reader: easyocr.Reader | None = None
_reader_config: dict[str, object] | None = None


def _ensure_languages(languages: Iterable[str] | None) -> list[str]:
    if languages is None:
        return list(_DEFAULT_LANGUAGES)
    langs = [lang.strip() for lang in languages if lang and lang.strip()]
    return langs or list(_DEFAULT_LANGUAGES)


def _get_reader(languages: Iterable[str] | None = None) -> easyocr.Reader:
    """Initialize and cache an EasyOCR reader in the current process."""

    global _reader
    global _reader_config

    langs = _ensure_languages(languages)
    quantize = _env_flag("OCR_QUANTIZE", default=_USE_QUANTIZE)
    recog_network = (os.getenv("OCR_RECOG_NETWORK") or _DEFAULT_RECOG_NETWORK).strip() or None

    if _reader is not None and _reader_config == {
        "languages": tuple(langs),
        "quantize": quantize,
        "recog_network": recog_network,
    }:
        return _reader

    kwargs: dict[str, object] = {"gpu": False, "verbose": False}
    if recog_network:
        kwargs["recog_network"] = recog_network

    if quantize:
        kwargs["quantize"] = True
    try:
        reader = easyocr.Reader(langs, **kwargs)
    except Exception:
        if quantize:
            logger.warning("Не удалось инициализировать EasyOCR с quantize=True, повторная попытка")
            kwargs.pop("quantize", None)
            reader = easyocr.Reader(langs, **kwargs)
            quantize = False
        else:
            raise

    logger.info(
        "EasyOCR reader инициализирован: языки=%s, quantize=%s, сеть=%s",
        ",".join(langs),
        quantize,
        recog_network or "default",
    )

    _reader = reader
    _reader_config = {
        "languages": tuple(langs),
        "quantize": quantize,
        "recog_network": recog_network,
    }
    return _reader


def release_reader() -> None:
    """Drop the cached EasyOCR reader so it can be recreated later."""

    global _reader
    global _reader_config
    if _reader is not None:
        logger.info("EasyOCR: освобождаем reader и связанные веса")
    _reader = None
    _reader_config = None
    gc.collect()
    # Вернём освобождённые страницы ОС (glibc по умолчанию держит их в кэше)
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:  # pragma: no cover - другие libc или ограничения окружения
        pass


def _prepare_image(image: np.ndarray) -> np.ndarray:
    if _MAX_IMAGE_DIM <= 0:
        return image

    height, width = image.shape[:2]
    max_side = max(height, width)
    if max_side <= _MAX_IMAGE_DIM:
        return image

    scale = _MAX_IMAGE_DIM / float(max_side)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    logger.debug(
        "EasyOCR: изображение уменьшено с %dx%d до %dx%d",
        width,
        height,
        new_width,
        new_height,
    )
    return resized


def extract_text(image_path: str, languages: Iterable[str] | None = None) -> str:
    """Read text from the provided image using EasyOCR."""

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Unable to read image: {path}")

    reader = _get_reader(languages)
    prepared = _prepare_image(image)
    same_object = prepared is image
    lines = reader.readtext(prepared, detail=0)
    if not same_object:
        del prepared
    del image
    gc.collect()
    return "\n".join(lines)
