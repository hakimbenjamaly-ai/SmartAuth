# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: builds the full program folder with Tesseract, language data and local models.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []
for folder in ("tesseract", "tessdata", "models"):
    p = ROOT / folder
    if p.exists():
        datas.append((str(p), folder))
icon = ROOT / "installer" / "app.ico"
if icon.exists():
    datas.append((str(icon), "."))

# packages that ship native DLLs / data files or use lazy imports
for pkg in ("pypdfium2", "pypdfium2_raw", "skimage", "pdfplumber", "pdfminer", "cv2"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
hidden += collect_submodules("app")
hidden += ["win32com", "win32com.client", "pythoncom", "pywintypes", "twain", "openpyxl", "xlrd",
           "pytesseract"]

# optional handwriting stack (only if installed on the build machine)
try:
    import transformers  # noqa: F401
    import torch  # noqa: F401
    for pkg in ("transformers", "tokenizers", "sentencepiece"):
        try:
            d, b, h = collect_all(pkg)
            datas += d; binaries += b; hidden += h
        except Exception:
            pass
except ImportError:
    pass

a = Analysis([str(ROOT / "main.py")], pathex=[str(ROOT)], datas=datas, binaries=binaries,
             hiddenimports=hidden, excludes=["tkinter", "matplotlib", "IPython", "pytest", "reportlab"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SmartAuth", console=False,
          icon=str(icon) if icon.exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SmartAuth")
