"""معالجة الصور: تحسين الجودة قبل القراءة، إزالة الخلفية والتشويش، تصحيح الميل."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread_any(path: str | Path) -> np.ndarray | None:
    """قراءة صورة من مسار قد يحتوي على أحرف عربية (cv2.imread يفشل معها على Windows)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        try:  # TIFF متعدد الصفحات أو صيغ أخرى عبر Pillow
            from PIL import Image
            with Image.open(str(path)) as im:
                img = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    return img


def imwrite_any(path: str | Path, img: np.ndarray) -> bool:
    ext = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(str(path))
    return ok


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def upscale_if_small(gray: np.ndarray, min_height: int = 1600) -> np.ndarray:
    h = gray.shape[0]
    if h < min_height:
        f = min(3.0, min_height / max(h, 1))
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return gray


def deskew(gray: np.ndarray) -> np.ndarray:
    """تصحيح ميل المستند بناءً على اتجاه أسطر النص."""
    inv = cv2.bitwise_not(gray)
    thr = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    if coords.shape[0] < 500:
        return gray
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    if angle > 45:
        angle -= 90
    if abs(angle) < 0.3 or abs(angle) > 15:
        return gray
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def enhance_for_ocr(img: np.ndarray) -> np.ndarray:
    """تحسين المستند قبل OCR: تدرج رمادي، تكبير، إزالة تشويش، توحيد الإضاءة، تصحيح الميل."""
    g = upscale_if_small(to_gray(img))
    g = cv2.fastNlMeansDenoising(g, None, h=10, templateWindowSize=7, searchWindowSize=21)
    # توحيد الإضاءة (إزالة الظلال والخلفية غير المنتظمة)
    bg = cv2.medianBlur(cv2.dilate(g, np.ones((7, 7), np.uint8)), 21)
    g = 255 - cv2.absdiff(g, bg)
    g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    g = deskew(g)
    return g


def binarize(gray: np.ndarray) -> np.ndarray:
    """ثنائية تكيفية: الحبر أسود على خلفية بيضاء."""
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 31, 15)
