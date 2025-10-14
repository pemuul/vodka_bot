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
    parser.add_argument("--output", required=True, help="Path to JSON file for results")
    return parser


def _emit(payload: dict[str, object], output_path: Path) -> None:
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    languages = list(args.languages) if args.languages else list(_DEFAULT_LANGUAGES)
    output_path = Path(args.output)

    image_path = Path(args.image)
    if not image_path.exists():
        _emit({"success": False, "error": f"image not found: {image_path}"}, output_path)
        return 0

    try:
        import easyocr  # type: ignore

        reader = easyocr.Reader(languages, gpu=False, verbose=False)
        lines = reader.readtext(str(image_path), detail=0)
        _emit({"success": True, "text": "\n".join(lines)}, output_path)
        return 0
    except Exception as exc:  # pragma: no cover - native libs safety net
        _emit({"success": False, "error": f"{exc.__class__.__name__}: {exc}"}, output_path)
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
