"""تنزيل النماذج والملفات اللازمة مرة واحدة على جهاز البناء (يحتاج إنترنت هنا فقط).

بعد التنزيل تُضمّن هذه الملفات في ملف التثبيت، ويعمل البرنامج دون إنترنت نهائياً.

الاستخدام:
    python tools/download_models.py --tessdata
    python tools/download_models.py --handwriting-eng microsoft/trocr-base-handwritten
    python tools/download_models.py --handwriting-ara <معرّف نموذج TrOCR عربي على HuggingFace أو مسار محلي>
"""
from __future__ import annotations

import argparse
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata"


def get_tessdata(langs=("ara", "eng", "osd")):
    out = ROOT / "tessdata"
    out.mkdir(exist_ok=True)
    for l in langs:
        dest = out / f"{l}.traineddata"
        if dest.exists():
            print("موجود:", dest); continue
        url = TESSDATA_URL.format(lang=l) if l != "osd" else \
            "https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata"
        print("تنزيل", url)
        urllib.request.urlretrieve(url, dest)


def get_trocr(repo_or_path: str, lang: str):
    out = ROOT / "models" / "handwriting" / lang
    src = Path(repo_or_path)
    if src.exists():
        shutil.copytree(src, out, dirs_exist_ok=True)
    else:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        TrOCRProcessor.from_pretrained(repo_or_path).save_pretrained(out)
        VisionEncoderDecoderModel.from_pretrained(repo_or_path).save_pretrained(out)
    print("تم حفظ النموذج في", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tessdata", action="store_true")
    ap.add_argument("--handwriting-eng")
    ap.add_argument("--handwriting-ara")
    a = ap.parse_args()
    if a.tessdata:
        get_tessdata()
    if a.handwriting_eng:
        get_trocr(a.handwriting_eng, "eng")
    if a.handwriting_ara:
        get_trocr(a.handwriting_ara, "ara")
