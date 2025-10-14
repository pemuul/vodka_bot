"""CLI helper executed in a separate process to run EasyOCR."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_DEFAULT_LANGUAGES: Sequence[str] = ("ru", "en")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run EasyOCR on a single image")
    parser.add_argument("--image", required=True, help="Path to the image file")
    parser.add_argument(
        "--lang",
        dest="languages",
        action="append",
        default=None,
        help="Language to use (can be specified multiple times)",
    )
    return parser


def _emit(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    languages = list(args.languages) if args.languages else list(_DEFAULT_LANGUAGES)

    image_path = Path(args.image)
    if not image_path.exists():
        _emit({"success": False, "error": f"image not found: {image_path}"})
        return 0

    try:
        import cv2  # type: ignore
        import easyocr  # type: ignore

        image = cv2.imread(str(image_path))
        if image is None:
            _emit({"success": False, "error": "image not readable"})
            return 0

        reader = easyocr.Reader(languages, gpu=False, verbose=False)
        lines = reader.readtext(image, detail=0)
        _emit({"success": True, "text": "\n".join(lines)})
        return 0
    except Exception as exc:  # pragma: no cover - native libs safety net
        _emit({"success": False, "error": f"{exc.__class__.__name__}: {exc}"})
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
