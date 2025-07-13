import easyocr
import cv2
import numpy as np

# Initialize EasyOCR once with Russian and English support.
# This reader is CPU-only to keep resource usage low.
_reader = easyocr.Reader(["ru", "en"], gpu=False)

def preprocess(img_bgr: np.ndarray) -> np.ndarray:
    """Basic preprocessing before OCR."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 31, 2)
    return gray


def extract_text(img_bgr: np.ndarray) -> str:
    """OCR helper that uses EasyOCR for both Russian and English text."""
    ready = preprocess(img_bgr)
    result = _reader.readtext(ready)
    return " ".join([r[1] for r in result])

