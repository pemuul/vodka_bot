"""EasyOCR helper that keeps the reader in-process for quick reuse."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Sequence

import cv2  # type: ignore
import easyocr  # type: ignore
import warnings

warnings.filterwarnings("ignore", message=".*pin_memory.*")

__all__ = ["extract_text", "release_reader"]

_DEFAULT_LANGUAGES: Sequence[str] = tuple(
    filter(None, (lang.strip() for lang in os.getenv("OCR_LANGUAGES", "ru,en").split(",")))
) or ("ru", "en")
_reader: easyocr.Reader | None = None


def _ensure_languages(languages: Iterable[str] | None) -> list[str]:
    if languages is None:
        return list(_DEFAULT_LANGUAGES)
    langs = [lang.strip() for lang in languages if lang and lang.strip()]
    return langs or list(_DEFAULT_LANGUAGES)


def _get_reader(languages: Iterable[str] | None = None) -> easyocr.Reader:
    """Initialize and cache an EasyOCR reader in the current process."""

    global _reader
    if _reader is None:
        _reader = easyocr.Reader(_ensure_languages(languages), gpu=False, verbose=False)
    return _reader


def release_reader() -> None:
    """Drop the cached EasyOCR reader so it can be recreated later."""

    global _reader
    _reader = None


def extract_text(image_path: str, languages: Iterable[str] | None = None) -> str:
    """Read text from the provided image using EasyOCR."""

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Unable to read image: {path}")

    reader = _get_reader(languages)
    lines = reader.readtext(image, detail=0)
    return "\n".join(lines)
