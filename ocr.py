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
    # enlarge image for better OCR accuracy
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    # reduce noise but keep edges sharp
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    # close small gaps between characters
    gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    gray = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 2
    )
    return gray


def extract_text_tesseract(img_bgr: np.ndarray) -> str:
    ready = preprocess(img_bgr)
    return pytesseract.image_to_string(ready, config=TSR_CONFIG)

