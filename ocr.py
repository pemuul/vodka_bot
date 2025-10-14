"""OCR helper using EasyOCR for Russian and English text."""

import gc
import warnings

warnings.filterwarnings("ignore", message=".*pin_memory.*")

import easyocr
import numpy as np

try:  # Torch is optional but helps to release cached tensors if present
    import torch
except Exception:  # pragma: no cover - torch may be absent or partially installed
    torch = None  # type: ignore

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


def release_reader() -> None:
    """Drop the cached OCR reader and release heavyweight resources."""

    global _reader
    if _reader is None:
        return

    try:
        # Reader instances keep references to neural network weights; removing
        # them allows Python's GC to reclaim the memory.
        _reader = None
        gc.collect()
        if torch is not None and hasattr(torch, "cuda"):
            try:
                torch.cuda.empty_cache()  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        # Releasing resources should never crash the worker; if something goes
        # wrong we simply continue with the existing reader.
        pass
