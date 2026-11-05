"""توليد توقيعات اصطناعية ومستندات تجريبية للاختبار."""
from __future__ import annotations

import cv2
import numpy as np


def _bezier(p, n=60):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = p
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def make_person_template(seed: int, strokes: int = 5):
    rng = np.random.default_rng(seed)
    curves = []
    x = 40.0
    for _ in range(strokes):
        pts = [np.array([x, rng.uniform(60, 140)])]
        for _ in range(3):
            pts.append(np.array([pts[-1][0] + rng.uniform(10, 50), rng.uniform(30, 170)]))
        curves.append(np.array(pts))
        x = pts[-1][0] - rng.uniform(0, 20)
    return curves


def render_signature(template, seed: int = 0, jitter: float = 2.0, angle: float = 0.0,
                     scale: float = 1.0, thickness: int = 3, noise: float = 0.0,
                     canvas=(220, 520), paper=245, shift=(0, 0)):
    rng = np.random.default_rng(seed)
    img = np.full(canvas, paper, np.uint8)
    for c in template:
        cc = c + rng.normal(0, jitter, c.shape)
        pts = _bezier(cc)
        pts = pts * scale + np.array(shift)
        cv2.polylines(img, [pts.astype(np.int32)], False, 20, thickness, cv2.LINE_AA)
    if angle:
        M = cv2.getRotationMatrix2D((canvas[1] / 2, canvas[0] / 2), angle, 1.0)
        img = cv2.warpAffine(img, M, (canvas[1], canvas[0]), borderValue=paper)
    if noise:
        n = rng.normal(0, noise, img.shape)
        img = np.clip(img.astype(float) + n, 0, 255).astype(np.uint8)
        # نقاط تشويش ماسح
        for _ in range(30):
            cv2.circle(img, (int(rng.uniform(0, canvas[1])), int(rng.uniform(0, canvas[0]))), 1, 90, -1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
