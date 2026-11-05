"""محرك مطابقة التوقيعات (محلي بالكامل، دون أي خدمة خارجية).

المراحل:
1. تنظيف الصورة: تدرج رمادي، إزالة التشويش، فصل الحبر عن الخلفية (Otsu)، حذف النقاط الصغيرة.
2. تحديد منطقة التوقيع وقصها، وتوحيد الحجم مع الحفاظ على النسبة.
3. استخراج خصائص بصرية: HOG (اتجاهات الخطوط) + LBP (الملمس) + كثافة المناطق + إسقاطات أفقية/عمودية
   + خصائص شكلية عامة.
4. حساب التشابه كمزيج موزون، ثم إعادة ترتيب أفضل النتائج بمطابقة نقاط ORB.

تنبيه: نسبة التشابه مؤشر بصري مساعد فقط، ولا تثبت أصالة التوقيع أو صحة نسبته قانونياً.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from skimage.feature import hog, local_binary_pattern

from .imaging import to_gray

FEATURE_VERSION = 2
NORM_H, NORM_W = 128, 256
DISCLAIMER = ("نسبة التشابه مؤشر بصري مساعد ناتج عن مقارنة آلية للصور، "
              "ولا تثبت أصالة التوقيع أو صحة نسبته قانونياً. القرار النهائي للمختص.")


# ------------------------------------------------------------------ cleaning
def extract_ink(img: np.ndarray) -> np.ndarray:
    """يعيد قناعاً ثنائياً للحبر (255 = حبر)."""
    g = to_gray(img)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    # إزالة الخلفية غير المنتظمة (ورق مصفر، ظلال)
    bg = cv2.medianBlur(cv2.dilate(g, np.ones((9, 9), np.uint8)), 31)
    diff = cv2.absdiff(bg, g)
    diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    _, ink = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # حذف النقاط الصغيرة (تشويش الماسح)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    min_area = max(8, int(ink.size * 0.00002))
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    ink = np.where(keep[labels], 255, 0).astype(np.uint8)
    return ink


def locate_signature(ink: np.ndarray, margin: int = 6) -> tuple[int, int, int, int]:
    """تحديد منطقة التوقيع: أكبر تجمع للحبر بعد دمج الأجزاء المتقاربة."""
    h, w = ink.shape
    if not ink.any():
        return 0, 0, w, h
    k = max(3, int(min(h, w) * 0.03))
    merged = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2 + 1, k + 1)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(merged, 8)
    if n <= 1:
        return 0, 0, w, h
    # اختيار التجمع الذي يحتوي أكبر كمية حبر فعلية
    best, best_ink = 1, -1
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        amount = int(np.count_nonzero(ink[y:y + bh, x:x + bw]))
        if amount > best_ink:
            best, best_ink = i, amount
    x, y, bw, bh, _ = stats[best]
    # ضم التجمعات المجاورة الكبيرة (توقيع مكون من أجزاء)
    x0, y0, x1, y1 = x, y, x + bw, y + bh
    for i in range(1, n):
        if i == best:
            continue
        xi, yi, wi, hi, ai = stats[i]
        near = (xi < x1 + bw * 0.5 and xi + wi > x0 - bw * 0.5 and
                yi < y1 + bh * 0.5 and yi + hi > y0 - bh * 0.5)
        if near and ai > 0.05 * stats[best][4]:
            x0, y0 = min(x0, xi), min(y0, yi)
            x1, y1 = max(x1, xi + wi), max(y1, yi + hi)
    return (max(0, x0 - margin), max(0, y0 - margin),
            min(w, x1 + margin) - max(0, x0 - margin), min(h, y1 + margin) - max(0, y0 - margin))


def normalize_signature(img: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """يعيد قناع حبر موحد الحجم (NORM_H×NORM_W) ومنطقة القص في الصورة الأصلية."""
    ink = extract_ink(img)
    x, y, w, h = locate_signature(ink)
    crop = ink[y:y + h, x:x + w]
    ys, xs = np.nonzero(crop)
    if len(xs):
        crop = crop[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ch, cw = crop.shape[:2]
    scale = min((NORM_W - 8) / max(cw, 1), (NORM_H - 8) / max(ch, 1))
    rs = cv2.resize(crop, (max(1, int(cw * scale)), max(1, int(ch * scale))), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((NORM_H, NORM_W), np.uint8)
    oy, ox = (NORM_H - rs.shape[0]) // 2, (NORM_W - rs.shape[1]) // 2
    canvas[oy:oy + rs.shape[0], ox:ox + rs.shape[1]] = rs
    _, canvas = cv2.threshold(canvas, 64, 255, cv2.THRESH_BINARY)
    return canvas, (x, y, w, h)


def cleaned_preview(img: np.ndarray) -> np.ndarray:
    """صورة معاينة نظيفة (حبر أسود على أبيض) مقصوصة على منطقة التوقيع."""
    ink = extract_ink(img)
    x, y, w, h = locate_signature(ink)
    return 255 - ink[y:y + h, x:x + w]


# ------------------------------------------------------------------ features
@dataclass
class SigFeatures:
    hog: np.ndarray
    lbp: np.ndarray
    zones: np.ndarray
    proj: np.ndarray
    shape: np.ndarray

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez_compressed(buf, hog=self.hog, lbp=self.lbp, zones=self.zones,
                            proj=self.proj, shape=self.shape, ver=np.array([FEATURE_VERSION]))
        return buf.getvalue()

    @staticmethod
    def from_bytes(b: bytes) -> "SigFeatures | None":
        try:
            z = np.load(io.BytesIO(b))
            if int(z["ver"][0]) != FEATURE_VERSION:
                return None
            return SigFeatures(z["hog"], z["lbp"], z["zones"], z["proj"], z["shape"])
        except Exception:
            return None


def _unit(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32).ravel()
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def compute_features(img: np.ndarray) -> SigFeatures:
    norm, _ = normalize_signature(img)
    # تنعيم بسيط لتقليل حساسية سمك القلم
    soft = cv2.GaussianBlur(norm, (5, 5), 0)
    h = hog(soft, orientations=9, pixels_per_cell=(16, 16), cells_per_block=(2, 2),
            block_norm="L2-Hys", feature_vector=True)
    # LBP على شبكة 2×4
    lbp = local_binary_pattern(soft, P=8, R=1, method="uniform")
    hists = []
    for gy in range(2):
        for gx in range(4):
            cell = lbp[gy * 64:(gy + 1) * 64, gx * 64:(gx + 1) * 64]
            msk = norm[gy * 64:(gy + 1) * 64, gx * 64:(gx + 1) * 64] > 0
            hh, _ = np.histogram(cell[msk] if msk.any() else cell, bins=10, range=(0, 10))
            hists.append(hh / max(hh.sum(), 1))
    lbp_v = np.concatenate(hists)
    # كثافة الحبر في المناطق 8×16
    small = cv2.resize(norm.astype(np.float32) / 255.0, (16, 8), interpolation=cv2.INTER_AREA)
    zones = small.ravel()
    # الإسقاطات
    b = (norm > 0).astype(np.float32)
    ph = cv2.resize(b.sum(axis=1).reshape(-1, 1), (1, 32), interpolation=cv2.INTER_AREA).ravel()
    pv = cv2.resize(b.sum(axis=0).reshape(1, -1), (64, 1), interpolation=cv2.INTER_AREA).ravel()
    proj = np.concatenate([ph / max(ph.max(), 1e-6), pv / max(pv.max(), 1e-6)])
    # خصائص شكلية
    ys, xs = np.nonzero(norm)
    if len(xs):
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        aspect = bw / max(bh, 1)
        density = len(xs) / max(bw * bh, 1)
        cx, cy = xs.mean() / NORM_W, ys.mean() / NORM_H
    else:
        aspect = density = cx = cy = 0.0
    n_comp = cv2.connectedComponents(norm)[0] - 1
    shape = np.array([aspect, density, cx, cy, min(n_comp, 40) / 40.0], np.float32)
    return SigFeatures(_unit(h), lbp_v.astype(np.float32), zones.astype(np.float32),
                       proj.astype(np.float32), shape)


# ---------------------------------------------------------------- similarity
def _cos(a, b) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _chi2_sim(a, b) -> float:
    d = 0.5 * np.sum((a - b) ** 2 / (a + b + 1e-9)) / (len(a) / 10)
    return float(max(0.0, 1.0 - d))


def _corr(a, b) -> float:
    a = a - a.mean(); b = b - b.mean()
    return max(0.0, _cos(a, b))


def similarity(f1: SigFeatures, f2: SigFeatures) -> float:
    """درجة تشابه بين 0 و 1."""
    s_hog = max(0.0, _cos(f1.hog, f2.hog))
    s_lbp = _chi2_sim(f1.lbp, f2.lbp)
    s_zone = _corr(f1.zones, f2.zones)
    s_proj = _corr(f1.proj, f2.proj)
    a1, a2 = f1.shape[0], f2.shape[0]
    s_aspect = float(np.exp(-abs(np.log((a1 + 1e-3) / (a2 + 1e-3))) * 1.5))
    s_dens = float(np.exp(-abs(f1.shape[1] - f2.shape[1]) * 6))
    raw = (0.40 * s_hog + 0.12 * s_lbp + 0.18 * s_zone + 0.15 * s_proj
           + 0.10 * s_aspect + 0.05 * s_dens)
    # معايرة (على عينات اختبار): الخام ~0.82 للتوقيع نفسه، ~0.42 لتوقيعات مختلفة
    cal = 1.0 / (1.0 + np.exp(-(raw - 0.56) * 12))
    return float(np.clip(cal, 0.0, 1.0))


def orb_score(img1: np.ndarray, img2: np.ndarray) -> float:
    """نسبة نقاط ORB المتطابقة هندسياً (0..1) - تستخدم لإعادة ترتيب أفضل النتائج."""
    a, _ = normalize_signature(img1)
    b, _ = normalize_signature(img2)
    a = cv2.resize(a, (NORM_W * 2, NORM_H * 2)); b = cv2.resize(b, (NORM_W * 2, NORM_H * 2))
    orb = cv2.ORB_create(nfeatures=500)
    k1, d1 = orb.detectAndCompute(a, None)
    k2, d2 = orb.detectAndCompute(b, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = bf.knnMatch(d1, d2, k=2)
    good = [m for m, *rest in pairs if rest and m.distance < 0.8 * rest[0].distance]
    if len(good) < 6:
        return len(good) / max(min(len(k1), len(k2)), 1)
    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=8.0)
    inl = int(mask.sum()) if mask is not None else 0
    return float(min(1.0, inl / max(min(len(k1), len(k2)) * 0.25, 1)))
