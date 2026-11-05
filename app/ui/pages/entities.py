"""تصنيفات الجهات والقوائم الفرعية، والدول والمدن."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget,
                               QListWidgetItem, QSpinBox, QSplitter, QTextEdit, QVBoxLayout, QWidget, QCheckBox,
                               QGroupBox)
from PySide6.QtCore import Qt

from ...core import permissions as P
from ..widgets import FormDialog, Page, Table, button, combo_fill, confirm, guarded, hbox, info
from .persons import PERSON_COLS


class EntitiesPage(Page):
    title = "الجهات وتصنيفاتها"
    subtitle = "اختر تصنيفاً لعرض قائمته الفرعية (السفارات، القنصليات، الشركات، الوزارات، ...)."

    def __init__(self, ctx):
        super().__init__(ctx)
        s = ctx.session
        self.admin = s.has(P.MANAGE_ENTITIES)
        split = QSplitter(Qt.Horizontal)
        left = QGroupBox("التصنيفات"); lv = QVBoxLayout(left)
        self.cats = QListWidget(); self.cats.currentRowChanged.connect(lambda _: self.load_entities())
        lv.addWidget(self.cats)
        if self.admin:
            lv.addLayout(hbox(button("إضافة", self.add_cat, "accent"), button("تعديل", self.edit_cat, "secondary"),
                              button("حذف", self.del_cat, "danger")))
        split.addWidget(left)
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.q = QLineEdit(); self.q.setPlaceholderText("بحث في أسماء الجهات...")
        self.q.textChanged.connect(lambda _: self.load_entities())
        self.country = QComboBox(); self.country.currentIndexChanged.connect(lambda _: self.load_entities())
        rv.addLayout(hbox(self.q, self.country))
        self.table = Table([("name", "اسم الجهة"), ("category_name", "التصنيف"), ("country_name", "الدولة"),
                            ("city_name", "المدينة"), ("phone", "الهاتف"), ("email", "البريد"),
                            ("persons_count", "عدد المخولين")])
        self.table.doubleClicked.connect(self.show_persons)
        rv.addWidget(self.table, 1)
        bar = [button("عرض الأشخاص المخولين", self.show_persons, "secondary")]
        if self.admin:
            bar += [button("إضافة جهة", self.add_entity, "accent"), button("تعديل", self.edit_entity, "secondary"),
                    button("حذف", self.del_entity, "danger"), None,
                    button("الدول والمدن", self.countries, "secondary")]
        else:
            bar.append(None)
        rv.addLayout(hbox(*bar))
        split.addWidget(right)
        split.setSizes([260, 900])
        self.layout_.addWidget(split, 1)

    def on_show(self):
        self.load_cats()
        combo_fill(self.country, self.sv.catalog.countries(), "name_ar", "كل الدول")

    def load_cats(self):
        cur = self.cats.currentItem().data(Qt.UserRole) if self.cats.currentItem() else None
        self.cats.blockSignals(True)
        self.cats.clear()
        all_ = QListWidgetItem("جميع التصنيفات"); all_.setData(Qt.UserRole, None); self.cats.addItem(all_)
        for c in self.sv.catalog.categories(active_only=not self.admin):
            it = QListWidgetItem(f"{c['name']}  ({c['n']})" + ("" if c["is_active"] else " - موقوف"))
            it.setData(Qt.UserRole, dict(c))
            self.cats.addItem(it)
            if cur and cur["id"] == c["id"]:
                self.cats.setCurrentItem(it)
        if self.cats.currentRow() < 0:
            self.cats.setCurrentRow(0)
        self.cats.blockSignals(False)
        self.load_entities()

    def _cat(self):
        it = self.cats.currentItem()
        return it.data(Qt.UserRole) if it else None

    @guarded
    def load_entities(self):
        c = self._cat()
        self.table.fill(self.sv.catalog.entities(category_id=c["id"] if c else None,
                                                 country_id=self.country.currentData(), text=self.q.text().strip()))

    def show_persons(self, *_):
        e = self.table.current()
        if not e:
            return info(self, "اختر جهة")
        d = QDialog(self); d.setWindowTitle(f"الأشخاص المخولون - {e['name']}"); d.resize(900, 500)
        v = QVBoxLayout(d)
        t = Table(PERSON_COLS); t.fill(self.sv.persons.search(entity_id=e["id"]))
        from .persons import PersonProfileDialog
        t.doubleClicked.connect(lambda *_: t.current() and PersonProfileDialog(self.ctx, t.current()["id"], d).exec())
        v.addWidget(t)
        d.exec()

    # ----------------------------------------------------------- categories
    @guarded
    def add_cat(self):
        name, ok = QInputDialog.getText(self, "تصنيف جديد", "اسم التصنيف:")
        if ok and name.strip():
            self.sv.catalog.add_category(name.strip()); self.load_cats()

    @guarded
    def edit_cat(self):
        c = self._cat()
        if not c:
            return
        d = FormDialog("تعديل التصنيف", self)
        name = d.add("الاسم:", QLineEdit(c["name"]))
        order = d.add("الترتيب:", QSpinBox()); order.setRange(0, 9999); order.setValue(c["sort_order"])
        active = d.add("فعال:", QCheckBox()); active.setChecked(bool(c["is_active"]))
        if d.exec():
            self.sv.catalog.update_category(c["id"], name.text().strip(), order.value(), int(active.isChecked()))
            self.load_cats()

    @guarded
    def del_cat(self):
        c = self._cat()
        if c and confirm(self, f"حذف التصنيف ({c['name']})؟"):
            self.sv.catalog.delete_category(c["id"]); self.load_cats()

    # ------------------------------------------------------------- entities
    def _entity_dialog(self, e=None):
        cat = self.sv.catalog
        d = FormDialog("بيانات الجهة", self)
        cb = d.add("التصنيف *:", QComboBox()); combo_fill(cb, cat.categories(), "name", empty=None)
        name = d.add("اسم الجهة *:", QLineEdit())
        name_en = d.add("الاسم بالإنجليزية:", QLineEdit())
        co = d.add("الدولة:", QComboBox()); combo_fill(co, cat.countries(), "name_ar", "— بدون —")
        ci = d.add("المدينة:", QComboBox())
        co.currentIndexChanged.connect(lambda _: combo_fill(ci, cat.cities(co.currentData()) if co.currentData()
                                                            else [], "name", "— بدون —"))
        combo_fill(ci, [], "name", "— بدون —")
        addr = d.add("العنوان:", QLineEdit()); phone = d.add("الهاتف:", QLineEdit())
        email = d.add("البريد:", QLineEdit()); notes = d.add("ملاحظات:", QTextEdit()); notes.setFixedHeight(60)
        active = d.add("فعالة:", QCheckBox()); active.setChecked(True)
        c = self._cat()
        if c:
            cb.setCurrentIndex(max(0, cb.findData(c["id"])))
        if e:
            cb.setCurrentIndex(max(0, cb.findData(e["category_id"])))
            name.setText(e["name"] or ""); name_en.setText(e["name_en"] or "")
            co.setCurrentIndex(max(0, co.findData(e["country_id"])))
            ci.setCurrentIndex(max(0, ci.findData(e["city_id"])))
            addr.setText(e["address"] or ""); phone.setText(e["phone"] or ""); email.setText(e["email"] or "")
            notes.setPlainText(e["notes"] or ""); active.setChecked(bool(e["is_active"]))
        if not d.exec():
            return None
        return dict(category_id=cb.currentData(), name=name.text().strip(), name_en=name_en.text().strip() or None,
                    country_id=co.currentData(), city_id=ci.currentData(), address=addr.text().strip() or None,
                    phone=phone.text().strip() or None, email=email.text().strip() or None,
                    notes=notes.toPlainText().strip() or None, is_active=int(active.isChecked()))

    @guarded
    def add_entity(self):
        data = self._entity_dialog()
        if data:
            self.sv.catalog.add_entity(**data); self.load_cats()

    @guarded
    def edit_entity(self):
        e = self.table.current()
        if not e:
            return info(self, "اختر جهة")
        data = self._entity_dialog(e)
        if data:
            self.sv.catalog.update_entity(e["id"], **data); self.load_cats()

    @guarded
    def del_entity(self):
        e = self.table.current()
        if e and confirm(self, f"حذف الجهة ({e['name']})؟ سيبقى الأشخاص المرتبطون بدون جهة."):
            self.sv.catalog.delete_entity(e["id"]); self.load_cats()

    def countries(self):
        CountriesDialog(self.ctx, self).exec()
        combo_fill(self.country, self.sv.catalog.countries(), "name_ar", "كل الدول")


class CountriesDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.sv = ctx.services
        self.setWindowTitle("إدارة الدول والمدن"); self.resize(760, 480)
        h = QHBoxLayout(self)
        l = QVBoxLayout(); r = QVBoxLayout()
        self.ct = Table([("name_ar", "الدولة"), ("name_en", "English"), ("iso2", "الرمز")])
        self.ct.itemSelectionChanged.connect(self.load_cities)
        l.addWidget(self.ct)
        l.addLayout(hbox(button("إضافة دولة", self.add_country, "accent"),
                         button("تعديل", self.edit_country, "secondary"), button("حذف", self.del_country, "danger")))
        self.cit = Table([("name", "المدينة")])
        r.addWidget(self.cit)
        r.addLayout(hbox(button("إضافة مدينة", self.add_city, "accent"), button("حذف", self.del_city, "danger")))
        h.addLayout(l, 3); h.addLayout(r, 2)
        self.load()

    def load(self):
        self.ct.fill(self.sv.catalog.countries()); self.load_cities()

    def load_cities(self):
        c = self.ct.current()
        self.cit.fill(self.sv.catalog.cities(c["id"]) if c else [])

    def _country_form(self, c=None):
        d = FormDialog("بيانات الدولة", self)
        a = d.add("الاسم بالعربية:", QLineEdit(c["name_ar"] if c else ""))
        e = d.add("الاسم بالإنجليزية:", QLineEdit((c["name_en"] or "") if c else ""))
        i = d.add("رمز ISO:", QLineEdit((c["iso2"] or "") if c else "")); i.setMaxLength(2)
        return (a.text().strip(), e.text().strip(), i.text().strip()) if d.exec() else None

    @guarded
    def add_country(self):
        v = self._country_form()
        if v and v[0]:
            self.sv.catalog.add_country(*v); self.load()

    @guarded
    def edit_country(self):
        c = self.ct.current()
        v = self._country_form(c) if c else None
        if v:
            self.sv.catalog.update_country(c["id"], *v); self.load()

    @guarded
    def del_country(self):
        c = self.ct.current()
        if c and confirm(self, f"حذف ({c['name_ar']}) ومدنها؟"):
            self.sv.catalog.delete_country(c["id"]); self.load()

    @guarded
    def add_city(self):
        c = self.ct.current()
        if not c:
            return info(self, "اختر دولة أولاً")
        n, ok = QInputDialog.getText(self, "مدينة جديدة", f"اسم المدينة في {c['name_ar']}:")
        if ok and n.strip():
            self.sv.catalog.add_city(c["id"], n.strip()); self.load_cities()

    @guarded
    def del_city(self):
        c = self.cit.current()
        if c and confirm(self, f"حذف ({c['name']})؟"):
            self.sv.catalog.delete_city(c["id"]); self.load_cities()
