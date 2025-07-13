"""OCR helper using EasyOCR for Russian and English text."""

import easyocr
import numpy as np

_reader: easyocr.Reader | None = None


def _get_reader() -> easyocr.Reader:
    """Initialize and cache the EasyOCR reader."""
    global _reader
    if _reader is None:
        # initialize once without GPU for lower memory usage
        _reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _reader


def extract_text(img_bgr: np.ndarray) -> str:
    """Extract text from an image using EasyOCR."""
    reader = _get_reader()
    lines = reader.readtext(img_bgr, detail=0)  # list of strings
    return "\n".join(lines)
