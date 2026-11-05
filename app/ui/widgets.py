"""عناصر واجهة مشتركة."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable, Sequence

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressDialog,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.db import PermissionDenied


def button(text: str, slot: Callable | None = None, kind: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def info(parent, msg: str, title: str = "تنبيه"):
    QMessageBox.information(parent, title, msg)


def error(parent, exc: Exception | str, title: str = "خطأ"):
    msg = str(exc)
    if isinstance(exc, PermissionDenied):
        title = "صلاحية مرفوضة"
    QMessageBox.critical(parent, title, msg)


def confirm(parent, msg: str, title: str = "تأكيد") -> bool:
    box = QMessageBox(QMessageBox.Question, title, msg, QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("نعم")
    box.button(QMessageBox.No).setText("لا")
    return box.exec() == QMessageBox.Yes


def guarded(fn: Callable) -> Callable:
    """يلتقط الاستثناءات ويعرضها بالعربية بدل إغلاق البرنامج."""
    def wrapper(self, *a, **kw):
        try:
            return fn(self, *a[:fn.__code__.co_argcount - 1], **kw)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            error(self, e)
    wrapper.__name__ = fn.__name__
    return wrapper


class Header(QFrame):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setObjectName("Header")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 10)
        t = QLabel(title); t.setObjectName("Title")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle); s.setObjectName("Subtitle"); s.setWordWrap(True)
            lay.addWidget(s)


class Page(QWidget):
    """صفحة أساسية مع ترويسة."""
    title = ""
    subtitle = ""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.sv = ctx.services
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(Header(self.title, self.subtitle))
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(16, 14, 16, 14)
        outer.addWidget(self.body, 1)

    def on_show(self):
        """يستدعى عند فتح الصفحة."""


class Table(QTableWidget):
    """جدول للقراءة يملأ من صفوف قاموسية."""

    def __init__(self, columns: Sequence[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self.setColumnCount(len(self.columns))
        self.setHorizontalHeaderLabels([c[1] for c in self.columns])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.rows: list[dict] = []

    def fill(self, rows):
        self.rows = [dict(r) for r in rows]
        self.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for j, (key, _) in enumerate(self.columns):
                v = r.get(key)
                it = QTableWidgetItem("" if v is None else str(v))
                it.setData(Qt.UserRole, r)
                self.setItem(i, j, it)
        self.resizeColumnsToContents()

    def current(self) -> dict | None:
        i = self.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None


def pixmap_from_path(path: str | Path, max_w: int = 420, max_h: int = 260) -> QPixmap:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(str(p))
            pil = doc[0].render(scale=1.5).to_pil().convert("RGB")
            doc.close()
            qi = QImage(pil.tobytes(), pil.width, pil.height, pil.width * 3, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(qi)
        except Exception:
            pm = QPixmap()
    else:
        pm = QPixmap(str(p))
        if pm.isNull():
            from ..engine.imaging import imread_any
            img = imread_any(p)
            if img is not None:
                pm = pixmap_from_array(img, 10_000, 10_000)
    if pm.isNull():
        return pm
    return pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def pixmap_from_array(img, max_w: int = 420, max_h: int = 260) -> QPixmap:
    import cv2
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    qi = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qi).scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class ImageBox(QLabel):
    def __init__(self, caption: str = "", w: int = 380, h: int = 220):
        super().__init__()
        self._w, self._h = w, h
        self.setMinimumSize(w // 2, h // 2)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:white;border:1px dashed #B8C2CC;border-radius:6px;")
        self.setText(caption)
        self._caption = caption

    def show_path(self, path):
        pm = pixmap_from_path(path, self._w, self._h) if path else QPixmap()
        if pm.isNull():
            self.setText(self._caption or "لا توجد صورة")
        else:
            self.setPixmap(pm)

    def show_array(self, img):
        self.setPixmap(pixmap_from_array(img, self._w, self._h))


def combo_fill(cb: QComboBox, rows, label_key: str, empty: str | None = "الكل", id_key: str = "id"):
    cb.blockSignals(True)
    cb.clear()
    if empty is not None:
        cb.addItem(empty, None)
    for r in rows:
        cb.addItem(str(r[label_key]), r[id_key])
    cb.blockSignals(False)


class FormDialog(QDialog):
    """نافذة نموذج عامة."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.lay = QVBoxLayout(self)
        from PySide6.QtWidgets import QFormLayout
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.lay.addLayout(self.form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.lay.addWidget(bb)

    def add(self, label: str, w: QWidget) -> QWidget:
        self.form.addRow(label, w)
        return w


# ---------------------------------------------------------------- threads
class _Worker(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(int, int, str)

    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs

    def run(self):
        try:
            if self.kwargs.pop("_with_progress", False):
                self.kwargs["progress"] = lambda i, n, s: self.progress.emit(i, n, s)
            self.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(e)


def run_with_progress(parent: QWidget, title: str, fn: Callable, *args, on_done: Callable[[Any], None],
                      with_progress: bool = True, **kwargs):
    """تشغيل عملية طويلة في خيط منفصل مع نافذة تقدم."""
    dlg = QProgressDialog(title, None, 0, 0, parent)
    dlg.setWindowTitle("جاري التنفيذ")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setCancelButton(None)
    th = QThread(parent)
    if with_progress:
        kwargs["_with_progress"] = True
    w = _Worker(fn, args, kwargs)
    w.moveToThread(th)

    def prog(i, n, s):
        dlg.setMaximum(n); dlg.setValue(i); dlg.setLabelText(f"{title}\n{s}  ({i}/{n})")

    def finish(res):
        dlg.close(); th.quit(); on_done(res)

    def fail(e):
        dlg.close(); th.quit(); error(parent, e)

    w.progress.connect(prog)
    w.done.connect(finish)
    w.failed.connect(fail)
    th.started.connect(w.run)
    th.finished.connect(w.deleteLater)
    parent._bg = (th, w)  # منع جمع الكائنات أثناء التشغيل
    th.start()
    dlg.show()


def hbox(*widgets, stretch_last: bool = False) -> QHBoxLayout:
    h = QHBoxLayout()
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    return h
