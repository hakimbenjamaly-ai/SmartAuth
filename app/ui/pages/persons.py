"""البحث عن الأشخاص (بالاسم، الجهة، رقم الهاتف) وصفحة بيانات الشخص."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QScrollArea, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
                               QCheckBox, QDialog)

from ...core import permissions as P
from ...services.persons import AUTH_STATUS_LABELS
from ..widgets import (FormDialog, ImageBox, Page, Table, button, combo_fill, confirm, error, guarded,
                       hbox, info)

PERSON_COLS = [("full_name", "الاسم"), ("job_title", "الصفة الوظيفية"), ("entity_name", "الجهة"),
               ("category_name", "التصنيف"), ("country_name", "الدولة"), ("phone", "الهاتف"),
               ("auth_status_label", "حالة التفويض"), ("auth_end", "صلاحية التفويض حتى"),
               ("last_cert", "آخر تصديق")]


class PersonSearchPage(Page):
    title = "البحث عن الأشخاص المخولين"
    subtitle = "ابحث بالاسم أو الصفة أو الجهة أو رقم الهاتف، مع إمكانية التصفية حسب التصنيف والدولة."

    def __init__(self, ctx, mode: str = "all"):
        if mode == "phone":
            self.title, self.subtitle = "البحث باستخدام رقم الهاتف", "يقبل الصيغ المحلية والدولية والأرقام العربية."
        elif mode == "entity":
            self.title, self.subtitle = "البحث عن الجهات", "اختر التصنيف ثم الجهة لعرض الأشخاص المخولين لديها."
        super().__init__(ctx)
        self.mode = mode
        s = ctx.session
        box = QGroupBox("معايير البحث")
        g = QGridLayout(box)
        self.name = QLineEdit(); self.name.setPlaceholderText("الاسم أو الصفة الوظيفية")
        self.phone = QLineEdit(); self.phone.setPlaceholderText("مثال: 0912345678 أو +218912345678")
        self.entity_text = QLineEdit(); self.entity_text.setPlaceholderText("اسم الجهة")
        self.cat = QComboBox(); self.country = QComboBox(); self.entity = QComboBox()
        self.cat.currentIndexChanged.connect(self._load_entities)
        self.country.currentIndexChanged.connect(self._load_entities)
        row = 0
        if mode != "phone":
            g.addWidget(QLabel("الاسم:"), row, 0); g.addWidget(self.name, row, 1)
            g.addWidget(QLabel("الجهة:"), row, 2); g.addWidget(self.entity_text, row, 3); row += 1
        g.addWidget(QLabel("الهاتف:"), row, 0); g.addWidget(self.phone, row, 1); row += 1
        g.addWidget(QLabel("التصنيف:"), row, 0); g.addWidget(self.cat, row, 1)
        g.addWidget(QLabel("الدولة:"), row, 2); g.addWidget(self.country, row, 3); row += 1
        g.addWidget(QLabel("الجهة المحددة:"), row, 0); g.addWidget(self.entity, row, 1, 1, 3)
        for w in (self.name, self.phone, self.entity_text):
            w.returnPressed.connect(self.search)
        self.layout_.addWidget(box)

        bar = [button("بحث", self.search), button("مسح", self.clear, "secondary")]
        if s.has(P.EDIT_DATA):
            bar += [None, button("إضافة شخص", self.add_person, "accent"),
                    button("تعديل", self.edit_person, "secondary")]
        if s.has(P.DELETE_DATA):
            bar.append(button("حذف", self.delete_person, "danger"))
        if bar[-1] is not None and None not in bar:
            bar.append(None)
        self.layout_.addLayout(hbox(*bar))
        self.table = Table(PERSON_COLS)
        self.table.doubleClicked.connect(self.open_profile)
        self.layout_.addWidget(self.table, 1)
        self.count = QLabel("")
        self.layout_.addWidget(self.count)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            combo_fill(self.cat, self.sv.catalog.categories(), "name")
            combo_fill(self.country, self.sv.catalog.countries(), "name_ar")
            self._load_entities()
            self._loaded = True
            self.search()

    def _load_entities(self):
        try:
            rows = self.sv.catalog.entities(category_id=self.cat.currentData(), country_id=self.country.currentData())
            combo_fill(self.entity, rows, "name")
        except Exception as e:  # noqa: BLE001
            error(self, e)

    @guarded
    def search(self):
        rows = self.sv.persons.search(name=self.name.text().strip(), phone=self.phone.text().strip(),
                                      entity_id=self.entity.currentData(), category_id=self.cat.currentData(),
                                      country_id=self.country.currentData(),
                                      entity_text=self.entity_text.text().strip())
        self.table.fill(rows)
        self.count.setText(f"عدد النتائج: {len(rows)}")

    def clear(self):
        for w in (self.name, self.phone, self.entity_text):
            w.clear()
        for c in (self.cat, self.country, self.entity):
            c.setCurrentIndex(0)
        self.search()

    def open_profile(self, *_):
        r = self.table.current()
        if r:
            PersonProfileDialog(self.ctx, r["id"], self).exec()
            self.search()

    @guarded
    def add_person(self):
        d = PersonDialog(self.ctx, None, self)
        if d.exec():
            self.search()

    @guarded
    def edit_person(self):
        r = self.table.current()
        if not r:
            return info(self, "اختر شخصاً من الجدول")
        if PersonDialog(self.ctx, r["id"], self).exec():
            self.search()

    @guarded
    def delete_person(self):
        r = self.table.current()
        if r and confirm(self, f"حذف سجل ({r['full_name']}) نهائياً مع تفويضاته وسجلاته؟"):
            self.sv.persons.delete(r["id"])
            self.search()


class PersonDialog(FormDialog):
    def __init__(self, ctx, pid: int | None, parent=None):
        super().__init__("بيانات الشخص المخول", parent)
        self.ctx, self.pid = ctx, pid
        sv = ctx.services
        self.full_name = self.add("الاسم الكامل *:", QLineEdit())
        self.full_name_en = self.add("الاسم بالإنجليزية:", QLineEdit())
        self.job_title = self.add("الصفة الوظيفية:", QLineEdit())
        self.cat = self.add("التصنيف:", QComboBox())
        self.entity = self.add("الجهة:", QComboBox())
        self.phone = self.add("الهاتف:", QLineEdit())
        self.email = self.add("البريد الإلكتروني:", QLineEdit())
        self.notes = self.add("ملاحظات:", QTextEdit()); self.notes.setFixedHeight(70)
        combo_fill(self.cat, sv.catalog.categories(), "name", empty="— اختر —")
        self.cat.currentIndexChanged.connect(self._ents)
        self._ents()
        if pid:
            p = sv.persons.get(pid)
            for k in ("full_name", "full_name_en", "job_title", "phone", "email"):
                getattr(self, k).setText(p.get(k) or "")
            self.notes.setPlainText(p.get("notes") or "")
            if p.get("entity_id"):
                e = sv.catalog.entity(p["entity_id"])
                self.cat.setCurrentIndex(max(0, self.cat.findData(e["category_id"])))
                self._ents()
                self.entity.setCurrentIndex(max(0, self.entity.findData(p["entity_id"])))

    def _ents(self):
        combo_fill(self.entity, self.ctx.services.catalog.entities(category_id=self.cat.currentData())
                   if self.cat.currentData() else [], "name", empty="— بدون —")

    def accept(self):
        data = dict(full_name=self.full_name.text().strip(), full_name_en=self.full_name_en.text().strip() or None,
                    job_title=self.job_title.text().strip() or None, entity_id=self.entity.currentData(),
                    phone=self.phone.text().strip() or None, email=self.email.text().strip() or None,
                    notes=self.notes.toPlainText().strip() or None)
        try:
            if self.pid:
                self.ctx.services.persons.update(self.pid, **data)
            else:
                self.pid = self.ctx.services.persons.add(**data)
            super().accept()
        except Exception as e:  # noqa: BLE001
            error(self, e)


class PersonProfileDialog(QDialog):
    """صفحة بيانات الشخص كاملة: البيانات، التوقيعات، الأختام، التفويضات، سجل التصديقات."""

    def __init__(self, ctx, pid: int, parent=None):
        super().__init__(parent)
        self.ctx, self.pid, self.sv = ctx, pid, ctx.services
        self.setWindowTitle("بيانات الشخص المخول")
        self.resize(980, 700)
        self.lay = QVBoxLayout(self)
        self.reload()

    def reload(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        p = self.sv.persons.profile(self.pid)
        s = self.ctx.session
        head = QGroupBox(p["full_name"])
        g = QGridLayout(head)
        fields = [("الاسم بالإنجليزية", p.get("full_name_en")), ("الصفة الوظيفية", p.get("job_title")),
                  ("الجهة", p.get("entity_name")), ("التصنيف", p.get("category_name")),
                  ("الدولة", p.get("country_name")), ("الهاتف", p.get("phone")),
                  ("البريد الإلكتروني", p.get("email")), ("حالة التفويض", p.get("auth_status_label")),
                  ("صلاحية التفويض حتى", p.get("auth_end")), ("آخر تصديق", p.get("last_cert"))]
        for i, (k, v) in enumerate(fields):
            lab = QLabel(f"<b>{k}:</b> {v or '—'}")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(lab, i // 2, i % 2)
        self.lay.addWidget(head)

        tabs = QTabWidget()
        # التوقيعات والأختام
        imgs = QWidget(); il = QHBoxLayout(imgs)
        for title, items, kind in (("التوقيعات", p["signatures"], "sig"), ("الأختام", p["stamps"], "stamp")):
            gb = QGroupBox(title); v = QVBoxLayout(gb)
            sc = QScrollArea(); sc.setWidgetResizable(True)
            inner = QWidget(); iv = QVBoxLayout(inner)
            if not items:
                iv.addWidget(QLabel("لا توجد صور مؤرشفة"))
            for it in items:
                box = ImageBox("", 380, 180); box.show_path(it["image_path"])
                iv.addWidget(box)
                iv.addWidget(QLabel(f"أُرشف في: {it['created_at']}" +
                                    ("" if it.get("is_active", 1) else "  (غير فعال)")))
            iv.addStretch(1)
            sc.setWidget(inner); v.addWidget(sc)
            if s.has(P.EDIT_DATA):
                v.addWidget(button(f"إضافة صورة {'توقيع' if kind == 'sig' else 'ختم'}",
                                   lambda _=False, k=kind: self.add_image(k), "secondary"))
            il.addWidget(gb)
        tabs.addTab(imgs, "التوقيعات والأختام")
        # التفويضات
        aw = QWidget(); av = QVBoxLayout(aw)
        self.auth_t = Table([("entity_name", "الجهة"), ("start_date", "من"), ("end_date", "إلى"),
                             ("status_label", "الحالة"), ("notes", "ملاحظات")])
        self.auth_t.fill(p["authorizations"]); av.addWidget(self.auth_t)
        if s.has(P.EDIT_DATA):
            av.addLayout(hbox(button("إضافة تفويض", self.add_auth, "accent"),
                              button("حذف التفويض المحدد", self.del_auth, "danger"), None))
        tabs.addTab(aw, f"التفويضات ({len(p['authorizations'])})")
        # سجل التصديقات
        cw = QWidget(); cv = QVBoxLayout(cw)
        self.cert_t = Table([("cert_date", "تاريخ التصديق"), ("reference_no", "الرقم الإشاري"),
                             ("entity_name", "الجهة"), ("notes", "ملاحظات")])
        self.cert_t.fill(p["certifications"]); cv.addWidget(self.cert_t)
        if s.has(P.EDIT_DATA):
            cv.addLayout(hbox(button("إضافة سجل تصديق", self.add_cert, "accent"), None))
        tabs.addTab(cw, f"السجل التاريخي للتصديقات ({len(p['certifications'])})")
        self.lay.addWidget(tabs, 1)
        self.lay.addLayout(hbox(None, button("إغلاق", self.accept, "secondary")))

    @guarded
    def add_image(self, kind):
        f, _ = QFileDialog.getOpenFileName(self, "اختر الصورة", "", "صور (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if not f:
            return
        if kind == "sig":
            self.sv.signatures.enroll(self.pid, f)
        else:
            self.sv.persons.add_stamp(f, person_id=self.pid)
        self.reload()

    @guarded
    def add_auth(self):
        d = FormDialog("إضافة تفويض", self)
        st = d.add("تاريخ البداية:", QDateEdit(QDate.currentDate())); st.setCalendarPopup(True)
        has_end = d.add("له تاريخ انتهاء:", QCheckBox()); has_end.setChecked(True)
        en = d.add("تاريخ الانتهاء:", QDateEdit(QDate.currentDate().addYears(1))); en.setCalendarPopup(True)
        status = d.add("الحالة:", QComboBox())
        for k, v in AUTH_STATUS_LABELS.items():
            status.addItem(v, k)
        notes = d.add("ملاحظات:", QLineEdit())
        for w in (st, en):
            w.setDisplayFormat("yyyy-MM-dd")
        if d.exec():
            self.sv.persons.add_authorization(self.pid, st.date().toString("yyyy-MM-dd"),
                                              en.date().toString("yyyy-MM-dd") if has_end.isChecked() else None,
                                              status.currentData(), notes=notes.text())
            self.reload()

    @guarded
    def del_auth(self):
        r = self.auth_t.current()
        if r and confirm(self, "حذف التفويض المحدد؟"):
            self.sv.persons.delete_authorization(r["id"]); self.reload()

    @guarded
    def add_cert(self):
        d = FormDialog("إضافة سجل تصديق", self)
        dt = d.add("تاريخ التصديق:", QDateEdit(QDate.currentDate())); dt.setCalendarPopup(True)
        dt.setDisplayFormat("yyyy-MM-dd")
        ref = d.add("الرقم الإشاري:", QLineEdit())
        notes = d.add("ملاحظات:", QLineEdit())
        if d.exec():
            self.sv.persons.add_certification(self.pid, dt.date().toString("yyyy-MM-dd"), ref.text(),
                                              notes=notes.text())
            self.reload()
