"""مراجعة البيانات المستخرجة واعتمادها."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QPlainTextEdit, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
                               QFileDialog)

from ...engine.extract import FIELD_LABELS
from ..widgets import (ImageBox, Page, Table, button, combo_fill, confirm, error, guarded, hbox, info,
                       run_with_progress)

EDIT_FIELDS = ["full_name", "full_name_en", "job_title", "entity", "phone", "email", "date",
               "auth_start", "auth_end", "reference_no"]
STATUS_L = {"new": "جديد", "processing": "قيد القراءة", "processed": "مقروء", "partial": "مقروء جزئياً",
            "failed": "فشلت القراءة", "reviewed": "معتمد"}


class ReviewPage(Page):
    title = "مراجعة البيانات المستخرجة واعتمادها"
    subtitle = "راجع البيانات التي قرأها البرنامج من المستندات، وصحّحها، ثم اعتمدها لتصبح سجلات رسمية."

    def __init__(self, ctx):
        super().__init__(ctx)
        split = QSplitter(Qt.Horizontal)
        lw = QWidget(); lv = QVBoxLayout(lw); lv.setContentsMargins(0, 0, 0, 0)
        self.filter = QComboBox()
        self.filter.addItem("بانتظار المراجعة", "queue")
        for k, v in STATUS_L.items():
            self.filter.addItem(v, k)
        self.filter.addItem("كل المستندات", None)
        self.filter.currentIndexChanged.connect(lambda _: self.load())
        lv.addLayout(hbox(QLabel("عرض:"), self.filter, button("تحديث", self.load, "secondary")))
        self.docs = Table([("name", "المستند"), ("status_l", "الحالة"), ("pending", "حقول معلقة"),
                           ("conf", "ثقة القراءة"), ("source_name", "المصدر")])
        self.docs.itemSelectionChanged.connect(self.open_doc)
        lv.addWidget(self.docs, 1)
        lv.addLayout(hbox(button("إعادة قراءة المستند", self.reprocess, "secondary"),
                          button("استيراد ملف منفرد", self.import_one, "secondary")))
        split.addWidget(lw)

        rw = QWidget(); rv = QVBoxLayout(rw); rv.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()
        self.preview = ImageBox("معاينة المستند", 560, 640)
        sc = QScrollArea(); sc.setWidget(self.preview); sc.setWidgetResizable(True)
        tabs.addTab(sc, "المستند")
        self.text = QPlainTextEdit(); self.text.setReadOnly(True)
        tabs.addTab(self.text, "النص المقروء")
        split.addWidget(tabs)

        form_box = QGroupBox("البيانات المستخرجة (قابلة للتعديل)")
        fv = QVBoxLayout(form_box)
        self.warn = QLabel(""); self.warn.setObjectName("Disclaimer"); self.warn.setWordWrap(True); self.warn.hide()
        fv.addWidget(self.warn)
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignRight)
        self.inputs: dict[str, QComboBox] = {}
        for f in EDIT_FIELDS:
            cb = QComboBox(); cb.setEditable(True); cb.setMinimumWidth(280)
            self.inputs[f] = cb
            form.addRow(FIELD_LABELS[f] + ":", cb)
        self.cat = QComboBox()
        form.addRow("تصنيف الجهة:", self.cat)
        fv.addLayout(form)
        self.sig_box = QGroupBox("صور التوقيع المقترحة (اختر ما يُؤرشف)")
        self.sig_lay = QVBoxLayout(self.sig_box)
        fv.addWidget(self.sig_box)
        fv.addWidget(button("إضافة صورة توقيع من ملف", self.add_sig_file, "secondary"))
        fv.addLayout(hbox(button("اعتماد وحفظ", self.approve, "accent"),
                          button("رفض المستند", self.reject, "danger")))
        fv.addStretch(1)
        fsc = QScrollArea(); fsc.setWidget(form_box); fsc.setWidgetResizable(True)
        rv.addWidget(fsc)
        split.addWidget(rw)
        split.setSizes([330, 560, 430])
        self.layout_.addWidget(split, 1)
        self.doc = None
        self.sig_checks: list[tuple[QCheckBox, str]] = []

    def on_show(self):
        combo_fill(self.cat, self.sv.catalog.categories(), "name", "حسب مصدر البيانات")
        self.load()

    @guarded
    def load(self):
        f = self.filter.currentData()
        rows = self.sv.review.queue() if f == "queue" else self.sv.ingestion.documents(status=f)
        out = []
        for r in rows:
            d = dict(r)
            d["name"] = Path(d["original_path"]).name
            d["status_l"] = STATUS_L.get(d["status"], d["status"])
            d["conf"] = f"{d['ocr_confidence']:.0f}%" if d.get("ocr_confidence") is not None else "—"
            out.append(d)
        self.docs.fill(out)

    @guarded
    def open_doc(self):
        r = self.docs.current()
        if not r:
            return
        self.doc = self.sv.review.document(r["id"])
        d = self.doc
        self.preview.show_path(d["archive_path"] or d["original_path"])
        self.text.setPlainText(d.get("ocr_text") or "")
        if d["warnings"]:
            self.warn.setText("تنبيهات القراءة:\n• " + "\n• ".join(d["warnings"])); self.warn.show()
        else:
            self.warn.hide()
        for f, cb in self.inputs.items():
            cb.clear()
            vals = [e["value"] for e in d["extractions"] if e["field"] == f and e["status"] != "rejected"]
            if f == "date" and not vals:
                vals = []
            cb.addItems(vals)
            if not vals:
                cb.setEditText("")
        if d.get("category_id"):
            self.cat.setCurrentIndex(max(0, self.cat.findData(d["category_id"])))
        # التوقيعات المقترحة
        while self.sig_lay.count():
            w = self.sig_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.sig_checks = []
        for e in d["extractions"]:
            if e["field"] == "signature_candidate":
                self._add_sig(e["value"], checked=False)
        if not self.sig_checks:
            self.sig_lay.addWidget(QLabel("لم يتم اكتشاف توقيع تلقائياً"))

    def _add_sig(self, path, checked=True):
        ib = ImageBox("", 360, 120); ib.show_path(path)
        cb = QCheckBox("أرشفة هذه الصورة كتوقيع"); cb.setChecked(checked)
        self.sig_lay.addWidget(ib); self.sig_lay.addWidget(cb)
        self.sig_checks.append((cb, path))

    def add_sig_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "صورة التوقيع", "", "صور (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if f:
            self._add_sig(f, True)

    @guarded
    def approve(self):
        if not self.doc:
            return info(self, "اختر مستنداً")
        vals = {f: cb.currentText().strip() or None for f, cb in self.inputs.items()}
        if not vals.get("full_name"):
            vals["full_name"] = vals.get("full_name_en")
        if not vals.get("full_name"):
            return info(self, "يجب إدخال اسم الشخص قبل الاعتماد")
        sigs = [p for cb, p in self.sig_checks if cb.isChecked()]
        pid = self.sv.review.approve(self.doc["id"], vals, category_id=self.cat.currentData(),
                                     signature_paths=sigs)
        info(self, f"تم اعتماد البيانات وحفظها (رقم الشخص: {pid}).")
        self.doc = None
        self.load()

    @guarded
    def reject(self):
        if self.doc and confirm(self, "رفض كل البيانات المستخرجة من هذا المستند؟"):
            self.sv.review.reject([e["id"] for e in self.doc["extractions"]])
            self.load()

    def reprocess(self):
        r = self.docs.current()
        if not r:
            return info(self, "اختر مستنداً")
        run_with_progress(self, "إعادة قراءة المستند...", self.sv.ingestion.process_document, r["id"],
                          with_progress=False, on_done=lambda res: (self.load(), info(
                              self, "الحالة: " + STATUS_L.get(res["status"], res["status"]) +
                              ("\n\n" + "\n".join(res["warnings"]) if res["warnings"] else ""))))

    def import_one(self):
        f, _ = QFileDialog.getOpenFileName(self, "اختر مستنداً", "",
                                           "مستندات (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if not f:
            return
        try:
            did, new = self.sv.ingestion.import_file(f)
        except Exception as e:  # noqa: BLE001
            return error(self, e)
        if not new:
            return info(self, "هذا الملف مستورد سابقاً (نفس البصمة الرقمية).")
        run_with_progress(self, "قراءة المستند...", self.sv.ingestion.process_document, did,
                          with_progress=False, on_done=lambda _: self.load())
