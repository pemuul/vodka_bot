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
TRACE_PREFIX = "[OCR-TRACE]"

# Уменьшаем параллелизм в используемых библиотеках, чтобы снизить число арен glibc
try:  # pragma: no cover - зависит от версии OpenCV
    cv2.setNumThreads(1)
except Exception:
    pass
try:  # pragma: no cover - torch может отсутствовать в окружении
    import torch  # type: ignore

    torch.set_num_threads(int(os.getenv("TORCH_NUM_THREADS", "1")))
    if hasattr(torch, "set_num_interop_threads"):
        torch.set_num_interop_threads(int(os.getenv("TORCH_INTEROP_THREADS", "1")))
except Exception:
    pass


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    logger.info("%s _env_flag name=%s value=%s default=%s", TRACE_PREFIX, name, value, default)
    if value is None:
        return default
    result = value.strip().lower() in {"1", "true", "yes", "on"}
    logger.info("%s _env_flag result=%s", TRACE_PREFIX, result)
    return result


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    logger.info("%s _env_int name=%s raw=%s default=%s", TRACE_PREFIX, name, raw, default)
    if raw is None:
        return default
    try:
        value = max(0, int(raw))
        logger.info("%s _env_int parsed=%s", TRACE_PREFIX, value)
        return value
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
    logger.info("%s _ensure_languages input=%s", TRACE_PREFIX, languages)
    if languages is None:
        result = list(_DEFAULT_LANGUAGES)
        logger.info("%s _ensure_languages default=%s", TRACE_PREFIX, result)
        return result
    langs = [lang.strip() for lang in languages if lang and lang.strip()]
    if not langs:
        result = list(_DEFAULT_LANGUAGES)
        logger.info("%s _ensure_languages fallback=%s", TRACE_PREFIX, result)
        return result
    logger.info("%s _ensure_languages cleaned=%s", TRACE_PREFIX, langs)
    return langs


def _get_reader(languages: Iterable[str] | None = None) -> easyocr.Reader:
    """Initialize and cache an EasyOCR reader in the current process."""

    global _reader
    global _reader_config

    logger.info("%s _get_reader called languages=%s", TRACE_PREFIX, languages)
    langs = _ensure_languages(languages)
    quantize = _env_flag("OCR_QUANTIZE", default=_USE_QUANTIZE)
    recog_network = (os.getenv("OCR_RECOG_NETWORK") or _DEFAULT_RECOG_NETWORK).strip() or None
    logger.info(
        "%s _get_reader config langs=%s quantize=%s network=%s", TRACE_PREFIX, langs, quantize, recog_network
    )

    if _reader is not None and _reader_config == {
        "languages": tuple(langs),
        "quantize": quantize,
        "recog_network": recog_network,
    }:
        logger.info("%s _get_reader reuse existing reader", TRACE_PREFIX)
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
        "%s reader-init languages=%s quantize=%s network=%s", TRACE_PREFIX, ",".join(langs), quantize, recog_network or "default"
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
    logger.info("%s release_reader called has_reader=%s", TRACE_PREFIX, _reader is not None)
    if _reader is not None:
        logger.info("EasyOCR: освобождаем reader и связанные веса")
    _reader = None
    _reader_config = None
    gc.collect()
    logger.info("%s release_reader gc.collect completed", TRACE_PREFIX)
    # Вернём освобождённые страницы ОС (glibc по умолчанию держит их в кэше)
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
        logger.info("%s release_reader malloc_trim invoked", TRACE_PREFIX)
    except Exception:  # pragma: no cover - другие libc или ограничения окружения
        pass


def _prepare_image(image: np.ndarray) -> np.ndarray:
    logger.info("%s _prepare_image start shape=%s max_dim=%s", TRACE_PREFIX, getattr(image, "shape", None), _MAX_IMAGE_DIM)
    if _MAX_IMAGE_DIM <= 0:
        logger.info("%s _prepare_image skip resize", TRACE_PREFIX)
        return image

    height, width = image.shape[:2]
    max_side = max(height, width)
    if max_side <= _MAX_IMAGE_DIM:
        logger.info("%s _prepare_image within limit max_side=%s", TRACE_PREFIX, max_side)
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
    logger.info(
        "%s _prepare_image resized from %sx%s to %sx%s", TRACE_PREFIX, width, height, new_width, new_height
    )
    return resized


def extract_text(image_path: str, languages: Iterable[str] | None = None) -> str:
    """Read text from the provided image using EasyOCR."""

    path = Path(image_path)
    logger.info("%s extract_text start path=%s languages=%s", TRACE_PREFIX, path, languages)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Unable to read image: {path}")

    logger.info("%s extract_text image-loaded shape=%s", TRACE_PREFIX, getattr(image, "shape", None))
    reader = _get_reader(languages)
    prepared = _prepare_image(image)
    same_object = prepared is image
    logger.info("%s extract_text calling readtext same_object=%s", TRACE_PREFIX, same_object)
    lines = reader.readtext(prepared, detail=0)
    logger.info("%s extract_text readtext-lines=%s", TRACE_PREFIX, len(lines))
    if not same_object:
        del prepared
    del image
    gc.collect()
    logger.info("%s extract_text gc.collect done", TRACE_PREFIX)
    return "\n".join(lines)
