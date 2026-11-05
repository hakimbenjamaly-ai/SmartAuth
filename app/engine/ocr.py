"""محرك قراءة المستندات المحلي.

- PDF نصي: استخراج طبقة النص مباشرة (pdfplumber).
- PDF ممسوح وصور (JPG/PNG/TIFF/BMP...): تحويل لصور، تحسين الجودة، ثم Tesseract (ara+eng).
- الكتابة اليدوية: الأسطر ذات الثقة المنخفضة تُمرر إلى نموذج محلي متخصص للتعرف على
  الكتابة اليدوية (TrOCR بصيغة HuggingFace محفوظ في مجلد models/handwriting/<lang>).
  إذا لم يكن النموذج مثبتاً تُسجل تحذيرات واضحة بالأجزاء غير المقروءة.

لا يتم أي اتصال بالإنترنت: النماذج تُحمّل بـ local_files_only=True.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .imaging import binarize, enhance_for_ocr, imread_any, to_gray

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif", ".jp2"}
PDF_EXT = {".pdf"}
LOW_CONF = 60       # أقل ثقة مقبولة لسطر مطبوع
MIN_TEXT_LAYER = 40  # أقل عدد أحرف لاعتبار صفحة PDF نصية

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


@dataclass
class OcrLine:
    text: str
    conf: float
    bbox: tuple[int, int, int, int]
    engine: str
    page: int


@dataclass
class OcrPage:
    page: int
    text: str
    lines: list[OcrLine] = field(default_factory=list)
    source: str = "ocr"        # text_layer | ocr
    image: np.ndarray | None = None


@dataclass
class OcrResult:
    pages: list[OcrPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    engines: set[str] = field(default_factory=set)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def confidence(self) -> float:
        ls = [l.conf for p in self.pages for l in p.lines if l.text.strip()]
        if not ls:
            return 100.0 if any(p.source == "text_layer" for p in self.pages) else 0.0
        return float(np.mean(ls))


# ------------------------------------------------------------------ tesseract
def configure_tesseract(tessdata_dir: Path | None = None) -> bool:
    import pytesseract
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(base / "tesseract" / "tesseract.exe")
    here = Path(__file__).resolve().parents[2]
    candidates += [here / "tesseract" / "tesseract.exe",
                   Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")]
    for c in candidates:
        if c.exists():
            pytesseract.pytesseract.tesseract_cmd = str(c)
            if (c.parent / "tessdata").exists():
                os.environ["TESSDATA_PREFIX"] = str(c.parent / "tessdata")
            break
    if tessdata_dir and Path(tessdata_dir).exists():
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    return shutil.which(pytesseract.pytesseract.tesseract_cmd) is not None or \
        Path(pytesseract.pytesseract.tesseract_cmd).exists()


def tesseract_lines(gray: np.ndarray, page: int, lang: str = "ara+eng") -> list[OcrLine]:
    import pytesseract
    data = pytesseract.image_to_data(gray, lang=lang, config="--oem 1 --psm 3",
                                     output_type=pytesseract.Output.DICT)
    groups: dict[tuple, list[int]] = {}
    for i, w in enumerate(data["text"]):
        if not str(w).strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append(i)
    lines = []
    for key in sorted(groups):
        idx = groups[key]
        words = [data["text"][i] for i in idx]
        confs = [float(data["conf"][i]) for i in idx if float(data["conf"][i]) >= 0]
        xs = [data["left"][i] for i in idx]; ys = [data["top"][i] for i in idx]
        x2 = [data["left"][i] + data["width"][i] for i in idx]
        y2 = [data["top"][i] + data["height"][i] for i in idx]
        lines.append(OcrLine(" ".join(words), float(np.mean(confs)) if confs else 0.0,
                             (min(xs), min(ys), max(x2) - min(xs), max(y2) - min(ys)), "tesseract", page))
    return lines


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx)); iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / max(min(aw * ah, bw * bh), 1)


def merge_lines(a: list[OcrLine], b: list[OcrLine]) -> list[OcrLine]:
    """دمج نتيجتي OCR: لكل منطقة يؤخذ السطر الأعلى ثقة، وتضاف الأسطر غير الموجودة في الأخرى."""
    out = list(a)
    for lb in b:
        hit = [i for i, la in enumerate(out) if _overlap(la.bbox, lb.bbox) > 0.4]
        if not hit:
            out.append(lb)
        elif len(hit) == 1 and lb.conf > out[hit[0]].conf + 5 and len(lb.text) >= len(out[hit[0]].text) * 0.7:
            out[hit[0]] = lb
    return out


# --------------------------------------------------------------- handwriting
class HandwritingEngine:
    """واجهة محرك الكتابة اليدوية. يمكن استبدالها بأي نموذج محلي آخر."""
    name = "none"

    def available(self) -> bool:
        return False

    def recognize(self, line_img: np.ndarray) -> tuple[str, float]:
        raise NotImplementedError


class TrOCREngine(HandwritingEngine):
    """TrOCR محلي (VisionEncoderDecoder). المجلد يحتوي ملفات النموذج والمعالج بصيغة HuggingFace."""

    def __init__(self, model_dir: Path, name: str):
        self.model_dir = Path(model_dir)
        self.name = name
        self._model = self._proc = None
        self._err: str | None = None

    def available(self) -> bool:
        if not (self.model_dir / "config.json").exists():
            return False
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            return True
        except Exception as e:
            self._err = str(e)
            return False

    def _load(self):
        if self._model is None:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            self._proc = TrOCRProcessor.from_pretrained(self.model_dir, local_files_only=True)
            self._model = VisionEncoderDecoderModel.from_pretrained(self.model_dir, local_files_only=True)
            self._model.eval()

    def recognize(self, line_img: np.ndarray) -> tuple[str, float]:
        import torch
        from PIL import Image
        self._load()
        rgb = cv2.cvtColor(line_img if line_img.ndim == 3 else cv2.cvtColor(line_img, cv2.COLOR_GRAY2BGR),
                           cv2.COLOR_BGR2RGB)
        pix = self._proc(images=Image.fromarray(rgb), return_tensors="pt").pixel_values
        with torch.no_grad():
            out = self._model.generate(pix, max_new_tokens=64, output_scores=True,
                                       return_dict_in_generate=True)
        text = self._proc.batch_decode(out.sequences, skip_special_tokens=True)[0].strip()
        conf = 0.0
        if out.scores:
            probs = [float(torch.softmax(s, -1).max()) for s in out.scores]
            conf = float(np.mean(probs) * 100)
        return text, conf


def load_handwriting_engines(models_dir: Path) -> dict[str, HandwritingEngine]:
    """يبحث عن models/handwriting/ara و models/handwriting/eng."""
    engines = {}
    for lang in ("ara", "eng"):
        e = TrOCREngine(Path(models_dir) / "handwriting" / lang, f"trocr-{lang}")
        if e.available():
            engines[lang] = e
    return engines


_ARABIC = re.compile(r"[\u0600-\u06FF]")


def _guess_lang(text: str) -> str:
    return "ara" if _ARABIC.search(text or "") else "eng"


# ------------------------------------------------------------------ pipeline
class DocumentReader:
    def __init__(self, models_dir: Path | None = None, tessdata_dir: Path | None = None,
                 lang: str = "ara+eng", dpi: int = 300):
        self.lang = lang
        self.dpi = dpi
        self.tesseract_ok = configure_tesseract(tessdata_dir)
        self.hw = load_handwriting_engines(models_dir) if models_dir else {}

    def status(self) -> dict:
        return {"tesseract": self.tesseract_ok,
                "handwriting": {k: v.name for k, v in self.hw.items()}}

    # ------------------------------------------------------------ loading
    def _pdf_pages(self, path: Path, res: OcrResult) -> list[tuple[str, np.ndarray | None]]:
        import pdfplumber
        import pypdfium2 as pdfium
        out = []
        with pdfplumber.open(str(path)) as pdf:
            texts = [(p.extract_text() or "") for p in pdf.pages]
        doc = pdfium.PdfDocument(str(path))
        try:
            for i, t in enumerate(texts):
                img = None
                if len(t.strip()) < MIN_TEXT_LAYER:
                    page = doc[i]
                    pil = page.render(scale=self.dpi / 72).to_pil()
                    img = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
                out.append((t, img))
        finally:
            doc.close()
        return out

    def _image_pages(self, path: Path) -> list[np.ndarray]:
        from PIL import Image, ImageSequence
        pages = []
        try:
            with Image.open(str(path)) as im:
                for fr in ImageSequence.Iterator(im):
                    pages.append(cv2.cvtColor(np.array(fr.convert("RGB")), cv2.COLOR_RGB2BGR))
        except Exception:
            img = imread_any(path)
            if img is not None:
                pages.append(img)
        return pages

    # -------------------------------------------------------------- read
    def read(self, path: str | Path, keep_images: bool = False) -> OcrResult:
        path = Path(path)
        res = OcrResult()
        ext = path.suffix.lower()
        if ext in PDF_EXT:
            try:
                items = self._pdf_pages(path, res)
            except Exception as e:
                res.warnings.append(f"تعذر فتح ملف PDF: {e}")
                return res
            for i, (t, img) in enumerate(items, 1):
                if img is None:
                    res.pages.append(OcrPage(i, t.strip(), source="text_layer"))
                    res.engines.add("pdf_text")
                else:
                    res.pages.append(self._ocr_image(img, i, res, keep_images))
        elif ext in IMAGE_EXT:
            imgs = self._image_pages(path)
            if not imgs:
                res.warnings.append("تعذر قراءة الصورة (ملف تالف أو صيغة غير مدعومة)")
            for i, img in enumerate(imgs, 1):
                res.pages.append(self._ocr_image(img, i, res, keep_images))
        else:
            res.warnings.append(f"صيغة غير مدعومة للقراءة: {ext}")
        if res.pages and not res.text.strip():
            res.warnings.append("لم يتمكن البرنامج من قراءة أي نص من المستند")
        return res

    def _ocr_image(self, img: np.ndarray, page: int, res: OcrResult, keep: bool) -> OcrPage:
        if not self.tesseract_ok:
            res.warnings.append(f"الصفحة {page}: محرك OCR (Tesseract) غير مثبت؛ لم تتم القراءة")
            return OcrPage(page, "", image=img if keep else None)
        g = enhance_for_ocr(img)
        # قراءتان: الصورة المحسنة والصورة الرمادية الأصلية، ثم دمج الأسطر (Tesseract قد يُسقط
        # أسطراً مختلفة في كل نسخة، خاصة في الصفحات قليلة النص)
        g0 = to_gray(img)
        if g0.shape != g.shape:
            g0 = cv2.resize(g0, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_CUBIC)
        lines = merge_lines(tesseract_lines(g, page, self.lang), tesseract_lines(g0, page, self.lang))
        res.engines.add("tesseract")
        # الأسطر ضعيفة الثقة: محاولة بنموذج الكتابة اليدوية
        final: list[OcrLine] = []
        for ln in lines:
            if ln.conf >= LOW_CONF or not self.hw:
                final.append(ln)
                continue
            x, y, w, h = ln.bbox
            pad = max(4, h // 4)
            crop = g[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
            eng = self.hw.get(_guess_lang(ln.text)) or next(iter(self.hw.values()))
            try:
                t, c = eng.recognize(crop)
                res.engines.add(eng.name)
                final.append(OcrLine(t, c, ln.bbox, eng.name, page) if c > ln.conf and t else ln)
            except Exception as e:
                res.warnings.append(f"الصفحة {page}: فشل نموذج الكتابة اليدوية: {e}")
                final.append(ln)
        # مناطق الحبر التي لم يكتشفها Tesseract إطلاقاً (غالباً كتابة يدوية)
        missed = self._uncovered_ink_regions(g, final)
        for (x, y, w, h) in missed:
            # محاولة ثانية بـ Tesseract على السطر منفرداً (psm 7)
            t2, c2 = self._tess_single_line(g[y:y + h, x:x + w])
            if t2 and c2 >= 45:
                final.append(OcrLine(t2, c2, (x, y, w, h), "tesseract-line", page))
                continue
            if self.hw:
                crop = g[y:y + h, x:x + w]
                eng = self.hw.get("ara") or next(iter(self.hw.values()))
                try:
                    t, c = eng.recognize(crop)
                    if t:
                        final.append(OcrLine(t, c, (x, y, w, h), eng.name, page))
                        res.engines.add(eng.name)
                        continue
                except Exception:
                    pass
            res.warnings.append(f"الصفحة {page}: منطقة غير مقروءة (قد تكون كتابة يدوية أو توقيع) "
                                f"عند الموضع x={x}, y={y}, بحجم {w}×{h}")
        weak = [l for l in final if l.conf < LOW_CONF and l.text.strip()]
        if weak:
            res.warnings.append(f"الصفحة {page}: {len(weak)} سطر/أسطر بثقة قراءة منخفضة؛ يلزم مراجعتها")
        final.sort(key=lambda l: (l.bbox[1], -l.bbox[0]))
        text = "\n".join(l.text for l in final)
        return OcrPage(page, text, final, "ocr", img if keep else None)

    def _tess_single_line(self, crop: np.ndarray) -> tuple[str, float]:
        import pytesseract
        if crop.size == 0:
            return "", 0.0
        crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        try:
            d = pytesseract.image_to_data(crop, lang=self.lang, config="--oem 1 --psm 7",
                                          output_type=pytesseract.Output.DICT)
        except Exception:
            return "", 0.0
        words = [(w, float(c)) for w, c in zip(d["text"], d["conf"]) if str(w).strip() and float(c) >= 0]
        if not words:
            return "", 0.0
        return " ".join(w for w, _ in words), float(np.mean([c for _, c in words]))

    @staticmethod
    def _uncovered_ink_regions(gray: np.ndarray, lines: list[OcrLine], min_frac: float = 0.002):
        b = 255 - binarize(gray)
        mask = np.zeros_like(b)
        for l in lines:
            x, y, w, h = l.bbox
            mask[max(0, y - 5):y + h + 5, max(0, x - 5):x + w + 5] = 255
        rest = cv2.bitwise_and(b, cv2.bitwise_not(mask))
        rest = cv2.morphologyEx(rest, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        merged = cv2.dilate(rest, cv2.getStructuringElement(cv2.MORPH_RECT, (35, 15)))
        n, _, stats, _ = cv2.connectedComponentsWithStats(merged, 8)
        H, W = gray.shape
        out = []
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if a < H * W * min_frac or h < 15 or w < 30:
                continue
            ink = np.count_nonzero(rest[y:y + h, x:x + w])
            if ink < 150:
                continue
            out.append((int(x), int(y), int(w), int(h)))
        return out[:20]


def find_signature_candidates(img: np.ndarray, max_n: int = 3) -> list[tuple[int, int, int, int]]:
    """اقتراح مناطق التوقيع في صفحة مستند: تجمعات حبر كثيفة غير منتظمة في النصف السفلي."""
    g = to_gray(img)
    b = 255 - binarize(g)
    merged = cv2.dilate(b, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(merged, 8)
    H, W = g.shape
    cands = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if y < H * 0.4 or w < W * 0.08 or h < H * 0.02 or w > W * 0.7:
            continue
        roi = b[y:y + h, x:x + w]
        fill = np.count_nonzero(roi) / max(w * h, 1)
        # التوقيع: نسبة امتلاء متوسطة وارتفاع أكبر من سطر نص عادي
        if 0.02 < fill < 0.35:
            cands.append((fill * h, (int(x), int(y), int(w), int(h))))
    cands.sort(reverse=True)
    return [c for _, c in cands[:max_n]]
