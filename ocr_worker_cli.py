"""CLI helper executed in a subprocess to run EasyOCR with a fresh interpreter."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Sequence


def _parse_languages(raw: str) -> list[str]:
    langs = [lang.strip() for lang in raw.split(",") if lang.strip()]
    return langs or ["ru", "en"]


def _load_image(path: Path, max_dimension: int):
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"OpenCVImportError: {exc}") from exc

    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError("image not readable")

    if max_dimension > 0:
        height, width = image.shape[:2]
        max_dim = max(height, width)
        if max_dim > max_dimension:
            scale = max_dimension / float(max_dim)
            new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
            image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image


def _recognize(image, languages: Sequence[str]) -> list[str]:
    try:
        from easyocr import Reader  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"EasyOCRImportError: {exc}") from exc

    try:
        reader = Reader(list(languages), gpu=False, verbose=False)
        return reader.readtext(image, detail=0, paragraph=True)
    except Exception as exc:  # pragma: no cover - native errors
        raise RuntimeError(f"EasyOCRError: {exc}") from exc
    finally:
        del image
        gc.collect()


def _write_output(output: Path, success: bool, text: str | None = None, error: str | None = None) -> None:
    payload = {"success": success, "text": text, "error": error}
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EasyOCR once and dump JSON output")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--languages", default="ru,en")
    parser.add_argument("--max-dimension", type=int, default=0)
    args = parser.parse_args()

    languages = _parse_languages(args.languages)

    try:
        image = _load_image(args.image, args.max_dimension)
        lines = _recognize(image, languages)
    except Exception as exc:
        _write_output(args.output, False, error=str(exc))
        return 1

    text = "\n".join(line for line in lines if line)
    _write_output(args.output, True, text=text)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
