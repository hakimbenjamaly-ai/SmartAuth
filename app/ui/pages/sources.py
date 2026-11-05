"""إدارة مصادر البيانات وبدء قراءة الملفات."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QLineEdit, QPushButton

from ...services.sources import DEFAULT_TYPES
from ..widgets import FormDialog, Page, Table, button, combo_fill, confirm, guarded, hbox, info, run_with_progress


class SourcesPage(Page):
    title = "إدارة مصادر البيانات"
    subtitle = ("أضف مسارات المجلدات التي تحتوي على المستندات، واربط كل مسار بتصنيف الجهة. "
                "الملفات التي سبق استيرادها لا يعاد استيرادها (بصمة SHA-256).")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.table = Table([("name", "اسم مصدر البيانات"), ("category_name", "تصنيف الجهة"),
                            ("root_path", "المسار الرئيسي"), ("file_types", "أنواع الملفات"),
                            ("recursive_l", "المجلدات الفرعية"), ("status_l", "الحالة"),
                            ("docs_count", "المستندات"), ("last_scan", "آخر فحص")])
        self.layout_.addLayout(hbox(
            button("إضافة مسار", self.add, "accent"), button("تعديل مسار", self.edit, "secondary"),
            button("حذف مسار", self.delete, "danger"), None, button("فحص المسار", self.check, "secondary"),
            button("بدء قراءة الملفات", self.start)))
        self.layout_.addWidget(self.table, 1)
        self.status = self.ctx.services.ingestion.engine_status
        self.engine_lbl = button("حالة محركات القراءة", self.show_engines, "secondary")
        self.layout_.addLayout(hbox(self.engine_lbl, None))

    def on_show(self):
        self.load()

    @guarded
    def load(self):
        rows = []
        for r in self.sv.sources.list():
            d = dict(r)
            d["recursive_l"] = "نعم" if d["recursive"] else "لا"
            d["status_l"] = "فعال" if d["is_active"] else "موقوف"
            rows.append(d)
        self.table.fill(rows)

    def _dialog(self, s=None):
        d = FormDialog("مصدر بيانات", self)
        name = d.add("اسم مصدر البيانات:", QLineEdit(s["name"] if s else ""))
        cat = d.add("تصنيف الجهة:", QComboBox())
        combo_fill(cat, self.sv.catalog.categories(), "name", "— بدون —")
        path = QLineEdit(s["root_path"] if s else "")
        browse = QPushButton("استعراض..."); browse.setProperty("kind", "secondary")
        browse.clicked.connect(lambda: (lambda p: p and path.setText(p))(
            QFileDialog.getExistingDirectory(self, "اختر المجلد", path.text())))
        d.form.addRow("المسار الرئيسي:", hbox(path, browse))
        types = d.add("نوع الملفات:", QLineEdit(s["file_types"] if s else DEFAULT_TYPES))
        rec = d.add("قراءة المجلدات الفرعية:", QCheckBox()); rec.setChecked(bool(s["recursive"]) if s else True)
        act = d.add("المصدر فعال:", QCheckBox()); act.setChecked(bool(s["is_active"]) if s else True)
        if s:
            cat.setCurrentIndex(max(0, cat.findData(s["category_id"])))
        if not d.exec():
            return None
        return dict(name=name.text().strip(), category_id=cat.currentData(), root_path=path.text().strip(),
                    file_types=types.text().strip(), recursive=rec.isChecked(), is_active=act.isChecked())

    @guarded
    def add(self):
        v = self._dialog()
        if v:
            sid = self.sv.sources.add(**v)
            self.load()
            if confirm(self, "تمت إضافة المسار. هل تريد فحصه وقراءة ملفاته الآن؟"):
                self._start(sid)

    @guarded
    def edit(self):
        s = self.table.current()
        if not s:
            return info(self, "اختر مساراً")
        v = self._dialog(s)
        if v:
            v["recursive"] = int(v["recursive"]); v["is_active"] = int(v["is_active"])
            self.sv.sources.update(s["id"], **v); self.load()

    @guarded
    def delete(self):
        s = self.table.current()
        if s and confirm(self, f"حذف المسار ({s['name']})؟ المستندات المستوردة منه تبقى في الأرشيف."):
            self.sv.sources.delete(s["id"]); self.load()

    @guarded
    def check(self):
        s = self.table.current()
        if not s:
            return info(self, "اختر مساراً")
        r = self.sv.sources.check(s["id"])
        types = "، ".join(f"{k}: {v}" for k, v in sorted(r["by_type"].items())) or "لا توجد ملفات"
        info(self, f"{r['message']}\n\n{types}", "نتيجة فحص المسار")

    def start(self):
        s = self.table.current()
        if not s:
            return info(self, "اختر مساراً")
        if not s["is_active"]:
            return info(self, "هذا المصدر موقوف")
        self._start(s["id"])

    def _start(self, sid):
        ing = self.sv.ingestion

        def scanned(rep):
            msg = (f"الملفات المكتشفة: {rep.found}\nالجديدة: {rep.new}\nالمستوردة سابقاً (تم تجاهلها): "
                   f"{rep.duplicates}")
            if rep.errors:
                msg += f"\nأخطاء: {len(rep.errors)}\n" + "\n".join(rep.errors[:5])
            self.load()
            if rep.new and confirm(self, msg + "\n\nبدء قراءة المستندات الجديدة (OCR) الآن؟"):
                run_with_progress(self, "قراءة المستندات واستخراج البيانات...", ing.process_pending,
                                  source_id=sid, on_done=processed)
            else:
                info(self, msg)

        def processed(summary):
            self.load()
            info(self, f"اكتملت القراءة:\nمقروءة بالكامل: {summary.get('processed', 0)}\n"
                       f"مقروءة جزئياً: {summary.get('partial', 0)}\nفشلت قراءتها: {summary.get('failed', 0)}\n\n"
                       "انتقل إلى (مراجعة البيانات المستخرجة) لاعتمادها.")

        run_with_progress(self, "فحص المجلد واكتشاف المستندات...", ing.scan_source, sid, on_done=scanned)

    def show_engines(self):
        st = self.status()
        hw = st["handwriting"]
        info(self, f"OCR للنصوص المطبوعة (Tesseract): {'مثبت' if st['tesseract'] else 'غير مثبت'}\n"
                   f"نموذج الكتابة اليدوية العربية: {hw.get('ara', 'غير مثبت')}\n"
                   f"نموذج الكتابة اليدوية الإنجليزية: {hw.get('eng', 'غير مثبت')}", "محركات القراءة المحلية")
