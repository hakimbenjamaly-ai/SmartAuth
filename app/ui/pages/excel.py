"""ملفات Excel: عرض، تعديل، تنقل بين الأوراق، واستيراد الأشخاص (للمشغل الرئيسي فقط)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QInputDialog, QLabel, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QLineEdit)

from ..widgets import FormDialog, Page, Table, button, combo_fill, confirm, error, guarded, hbox, info

IMPORT_FIELDS = [("full_name", "الاسم *"), ("full_name_en", "الاسم بالإنجليزية"), ("job_title", "الصفة الوظيفية"),
                 ("entity", "الجهة"), ("country", "الدولة"), ("phone", "الهاتف"), ("email", "البريد"),
                 ("auth_start", "بداية التفويض"), ("auth_end", "نهاية التفويض")]


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class ExcelPage(Page):
    title = "ملفات Excel"
    subtitle = "عرض ملفات Excel وتعديلها والتنقل بين أوراقها. يُحفظ تلقائياً نسخة من الملف قبل كل حفظ."

    def __init__(self, ctx):
        super().__init__(ctx)
        split = QSplitter(Qt.Horizontal)
        lw = QWidget(); lv = QVBoxLayout(lw); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>ملفات Excel من مصادر البيانات</b>"))
        self.files = Table([("name", "الملف"), ("source_name", "المصدر")])
        self.files.doubleClicked.connect(self.open_selected)
        lv.addWidget(self.files, 1)
        lv.addLayout(hbox(button("فتح المحدد", self.open_selected), button("فتح ملف...", self.open_file, "secondary")))
        split.addWidget(lw)
        rw = QWidget(); rv = QVBoxLayout(rw); rv.setContentsMargins(0, 0, 0, 0)
        self.path_lbl = QLabel("لم يتم فتح ملف")
        rv.addWidget(self.path_lbl)
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.South)
        rv.addWidget(self.tabs, 1)
        self.b_save = button("حفظ التعديلات", self.save, "accent")
        rv.addLayout(hbox(self.b_save, button("ورقة جديدة", self.add_sheet, "secondary"),
                          button("إضافة صف", self.add_row, "secondary"), None,
                          button("استيراد الأشخاص من الورقة الحالية", self.import_persons)))
        split.addWidget(rw)
        split.setSizes([280, 1000])
        self.layout_.addWidget(split, 1)
        self.wb = None
        self._loading = False

    def on_show(self):
        self.load_files()

    @guarded
    def load_files(self):
        rows = []
        for r in self.sv.excel.list_files():
            d = dict(r); d["name"] = Path(d["original_path"]).name; rows.append(d)
        self.files.fill(rows)

    def open_selected(self, *_):
        r = self.files.current()
        if r:
            p = r["original_path"] if Path(r["original_path"]).exists() else r["archive_path"]
            self._open(p)

    def open_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "فتح ملف Excel", "", "Excel (*.xlsx *.xlsm *.xls)")
        if f:
            self._open(f)

    def _confirm_discard(self) -> bool:
        return not (self.wb and self.wb.dirty) or confirm(self, "توجد تعديلات غير محفوظة. تجاهلها؟")

    @guarded
    def _open(self, path):
        if not self._confirm_discard():
            return
        self.wb = self.sv.excel.open(path)
        self.path_lbl.setText(f"<b>الملف:</b> {path}" + ("  (للقراءة فقط)" if self.wb.readonly else ""))
        self.b_save.setEnabled(not self.wb.readonly)
        self.tabs.clear()
        for name in self.wb.sheet_names():
            self.tabs.addTab(self._sheet_widget(name), name)

    def _sheet_widget(self, name):
        rows = self.wb.read_sheet(name)
        ncol = max([len(r) for r in rows] + [10])
        t = QTableWidget(max(len(rows), 30), ncol)
        t.setLayoutDirection(Qt.LeftToRight if not any(
            isinstance(v, str) and any("؀" <= c <= "ۿ" for c in v) for r in rows[:5] for v in r)
            else Qt.RightToLeft)
        t.setHorizontalHeaderLabels([col_letter(i) for i in range(ncol)])
        self._loading = True
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                t.setItem(i, j, QTableWidgetItem("" if v is None else str(v)))
        self._loading = False
        t.setProperty("sheet", name)
        t.cellChanged.connect(lambda row, col, t=t: self._changed(t, row, col))
        t.resizeColumnsToContents()
        return t

    def _changed(self, t, row, col):
        if self._loading or not self.wb:
            return
        try:
            it = t.item(row, col)
            self.sv.excel.set_cell(self.wb, t.property("sheet"), row + 1, col + 1, it.text() if it else None)
        except Exception as e:  # noqa: BLE001
            error(self, e)

    @guarded
    def save(self):
        if self.wb:
            bk = self.sv.excel.save(self.wb)
            info(self, "تم الحفظ." + (f"\nنسخة سابقة محفوظة في:\n{bk}" if bk else ""))

    @guarded
    def add_sheet(self):
        if not self.wb:
            return
        n, ok = QInputDialog.getText(self, "ورقة جديدة", "اسم الورقة:")
        if ok and n.strip():
            self.wb.add_sheet(n.strip())
            self.tabs.addTab(self._sheet_widget(n.strip()), n.strip())

    def add_row(self):
        t = self.tabs.currentWidget()
        if t:
            t.insertRow(t.rowCount())

    @guarded
    def import_persons(self):
        if not self.wb:
            return info(self, "افتح ملفاً أولاً")
        sheet = self.tabs.tabText(self.tabs.currentIndex())
        rows = self.wb.read_sheet(sheet, 2)
        headers = [str(v) for v in rows[0]] if rows else []
        d = FormDialog(f"استيراد الأشخاص من الورقة ({sheet})", self)
        cat = d.add("تصنيف الجهة:", QComboBox()); combo_fill(cat, self.sv.catalog.categories(), "name", empty=None)
        ent = d.add("جهة افتراضية (اختياري):", QLineEdit())
        hdr = d.add("عدد صفوف العناوين:", QSpinBox()); hdr.setRange(0, 20); hdr.setValue(1)
        maps = {}
        for key, label in IMPORT_FIELDS:
            cb = QComboBox(); cb.addItem("— لا يوجد —", None)
            for i, h in enumerate(headers):
                cb.addItem(f"{col_letter(i)}: {h}", i)
            # مطابقة تلقائية حسب العنوان
            for i, h in enumerate(headers):
                if label.replace(" *", "") in h or (key == "full_name" and "الاسم" in h and "إنجليزي" not in h):
                    cb.setCurrentIndex(i + 1); break
            maps[key] = d.add(label + ":", cb)
        if not d.exec():
            return
        mapping = {k: cb.currentData() for k, cb in maps.items() if cb.currentData() is not None}
        if "full_name" not in mapping:
            return info(self, "يجب تحديد عمود الاسم")
        r = self.sv.excel.import_persons(self.wb, sheet, mapping, cat.currentData(), hdr.value(),
                                         ent.text().strip() or None)
        msg = f"تمت الإضافة: {r['added']}\nتم التحديث: {r['updated']}\nصفوف فارغة: {r['skipped']}"
        if r["errors"]:
            msg += "\n\nأخطاء:\n" + "\n".join(r["errors"][:10])
        info(self, msg, "نتيجة الاستيراد")
