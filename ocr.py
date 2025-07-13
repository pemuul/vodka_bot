import pytesseract
import cv2
import numpy as np

TSR_CONFIG = (
    "-l rus+eng "
    "--oem 1 "
    "--psm 6 "
    "-c preserve_interword_spaces=1"
)


def preprocess(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # reduce noise while preserving edges
    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    # enlarge small images to help OCR
    h, w = gray.shape[:2]
    if max(h, w) < 1000:
        scale = 1000.0 / max(h, w)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

    # close gaps between characters
    kernel = np.ones((3, 3), np.uint8)
    gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)

    # binarize image
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return thresh


def extract_text(img_bgr: np.ndarray) -> str:
    ready = preprocess(img_bgr)
    return pytesseract.image_to_string(ready, config=TSR_CONFIG)
