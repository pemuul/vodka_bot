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
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.medianBlur(g, 3)
    g = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 2
    )
    return g


def extract_text_tesseract(img_bgr: np.ndarray) -> str:
    ready = preprocess(img_bgr)
    return pytesseract.image_to_string(ready, config=TSR_CONFIG)

