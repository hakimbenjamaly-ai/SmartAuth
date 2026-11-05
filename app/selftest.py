"""فحص ذاتي للنسخة المبنية: يتحقق من أن كل المكونات المضمنة تعمل على الجهاز.

التشغيل: SmartAuth.exe --selftest   (النتيجة في selftest.log ورمز الخروج 0 عند النجاح)
يعمل في مجلد بيانات مؤقت فلا يمس بيانات المنظومة الحقيقية.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def run(log_path: Path | None = None) -> int:
    lines: list[str] = []
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            r = fn()
            lines.append(f"[OK]   {name}" + (f": {r}" if r else ""))
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"[FAIL] {name}: {e}\n{traceback.format_exc()}")

    tmp = Path(tempfile.mkdtemp(prefix="smartauth_selftest_"))
    os.environ["SMART_AUTH_HOME"] = str(tmp)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    state = {}

    def ctx_():
        from .core.context import AppContext
        c = AppContext(tmp)
        c.services.auth.create_initial_admin("admin", "Selftest@123")
        c.services.auth.login("admin", "Selftest@123")
        state["ctx"] = c
        return str(c.paths.db)

    def tesseract():
        import pytesseract
        r = state["ctx"].services.ingestion.engine_status()
        if not r["tesseract"]:
            raise RuntimeError("Tesseract غير موجود")
        langs = pytesseract.get_languages(config="")
        for need in ("ara", "eng"):
            if need not in langs:
                raise RuntimeError(f"ملف اللغة {need} غير موجود: {langs}")
        return f"{pytesseract.get_tesseract_version()} langs={','.join(langs)} hw={r['handwriting']}"

    def ocr():
        import cv2
        import numpy as np
        img = np.full((500, 1400, 3), 255, np.uint8)
        cv2.putText(img, "Name: Selftest Person", (60, 160), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        cv2.putText(img, "Email: test@example.ly", (60, 320), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        p = tmp / "ocr.png"
        cv2.imwrite(str(p), img)
        did, _ = state["ctx"].services.ingestion.import_file(p)
        state["ctx"].services.ingestion.process_document(did)
        t = state["ctx"].db.scalar("SELECT ocr_text FROM documents WHERE id=?", (did,)) or ""
        if "Selftest" not in t:
            raise RuntimeError(f"نص غير متوقع: {t!r}")
        return "قراءة صحيحة"

    def pdf():
        import pypdfium2  # noqa: F401
        import pdfplumber  # noqa: F401
        return "pypdfium2/pdfplumber"

    def signature():
        import cv2
        import numpy as np
        from .engine import signature as eng
        img = np.full((200, 500, 3), 245, np.uint8)
        cv2.polylines(img, [np.array([[40, 120], [120, 40], [200, 150], [300, 60], [420, 130]], np.int32)],
                      False, (20, 20, 20), 3)
        f = eng.compute_features(img)
        s = eng.similarity(f, eng.SigFeatures.from_bytes(f.to_bytes()))
        if s < 0.9:
            raise RuntimeError(f"تشابه ذاتي منخفض {s}")
        return f"self-similarity={s:.2f}"

    def excel():
        import openpyxl
        p = tmp / "t.xlsx"
        wb = openpyxl.Workbook(); wb.active.append(["الاسم"]); wb.save(p)
        return state["ctx"].services.excel.open(p).sheet_names()[0]

    def backup():
        return state["ctx"].services.backup.create(include_archive=False).name

    def ui():
        from PySide6.QtWidgets import QApplication
        from .ui import widgets
        from .ui.main_window import MainWindow
        from .ui.theme import QSS
        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setStyleSheet(QSS)
        c = state["ctx"]

        def _raise(parent, exc, title=""):
            raise exc if isinstance(exc, Exception) else RuntimeError(exc)
        old = widgets.error
        widgets.error = _raise
        try:
            counts = []
            for role in ("admin", "standard"):
                if role == "standard":
                    c.services.auth.create_user("u_selftest", "Selftest@123", "standard")
                    c.services.auth.logout(); c.services.auth.login("u_selftest", "Selftest@123")
                w = MainWindow(c)
                for i in range(len(w._factories)):
                    w.switch(i)
                counts.append(len(w._factories))
                w.close(); w.deleteLater()
            app.processEvents()
        finally:
            widgets.error = old
        return f"pages admin={counts[0]} standard={counts[1]}"

    for name, fn in (("قاعدة البيانات", ctx_), ("Tesseract وملفات اللغة", tesseract), ("قراءة OCR", ocr),
                     ("مكتبات PDF", pdf), ("محرك التوقيعات", signature), ("Excel", excel),
                     ("النسخ الاحتياطي", backup), ("الواجهة", ui)):
        if name != "قاعدة البيانات" and "ctx" not in state:
            lines.append(f"[SKIP] {name}"); continue
        step(name, fn)

    if "ctx" in state:
        state["ctx"].close()
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    text = "\n".join(lines)
    log_path = log_path or Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent / "selftest.log"
    try:
        Path(log_path).write_text(text, encoding="utf-8")
    except OSError:
        Path(tempfile.gettempdir(), "smartauth_selftest.log").write_text(text, encoding="utf-8")
    try:
        print(text)
    except Exception:  # noqa: BLE001
        pass
    return 0 if ok else 1
