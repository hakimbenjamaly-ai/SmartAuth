"""لوحة المعلومات، المستخدمون، النسخ الاحتياطي، سجل العمليات."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QLabel, QLineEdit,
                               QFrame, QVBoxLayout)

from ...core.permissions import ROLE_LABELS
from ..login import password_field
from ..theme import ACCENT, PRIMARY
from ..widgets import FormDialog, Page, Table, button, confirm, guarded, hbox, info, run_with_progress


class DashboardPage(Page):
    title = "لوحة المعلومات"
    subtitle = "ملخص محتوى المنظومة."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.grid = QGridLayout()
        self.layout_.addLayout(self.grid)
        self.layout_.addStretch(1)

    def on_show(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        db = self.ctx.db
        today = __import__("datetime").date.today().isoformat()
        soon = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
        stats = [
            ("الأشخاص المخولون", db.scalar("SELECT COUNT(*) FROM persons")),
            ("الجهات", db.scalar("SELECT COUNT(*) FROM entities")),
            ("التوقيعات المؤرشفة", db.scalar("SELECT COUNT(*) FROM signatures WHERE is_active=1")),
            ("الأختام", db.scalar("SELECT COUNT(*) FROM stamps")),
            ("المستندات المستوردة", db.scalar("SELECT COUNT(*) FROM documents")),
            ("بانتظار المراجعة", db.scalar("SELECT COUNT(DISTINCT document_id) FROM extractions WHERE status='pending'")),
            ("تفويضات تنتهي خلال 30 يوماً", db.scalar(
                "SELECT COUNT(*) FROM authorizations WHERE status='active' AND end_date BETWEEN ? AND ?", (today, soon))),
            ("تفويضات منتهية", db.scalar(
                "SELECT COUNT(*) FROM authorizations WHERE status='expired' OR (status='active' AND end_date < ?)",
                (today,))),
        ]
        for i, (k, v) in enumerate(stats):
            f = QFrame(); f.setStyleSheet(f"background:white;border:1px solid #D5DBE1;border-right:5px solid {ACCENT};"
                                          "border-radius:8px;")
            l = QVBoxLayout(f)
            a = QLabel(str(v or 0)); a.setStyleSheet(f"font-size:24pt;font-weight:bold;color:{PRIMARY};border:none;")
            b = QLabel(k); b.setStyleSheet("color:#6B7785;border:none;")
            l.addWidget(a); l.addWidget(b)
            self.grid.addWidget(f, i // 4, i % 4)


class UsersPage(Page):
    title = "المستخدمون والصلاحيات"
    subtitle = ("المشغل الرئيسي: صلاحيات كاملة. المستخدم العادي: بحث وعرض فقط دون Excel أو تعديل أو حذف أو إعدادات. "
                "الصلاحيات مفروضة داخل النظام وقاعدة البيانات.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.table = Table([("username", "اسم المستخدم"), ("full_name", "الاسم"), ("role_l", "نوع الحساب"),
                            ("active_l", "الحالة"), ("last_login", "آخر دخول"), ("created_at", "تاريخ الإنشاء")])
        self.layout_.addLayout(hbox(button("مستخدم جديد", self.add, "accent"), button("تعديل", self.edit, "secondary"),
                                    button("إعادة تعيين كلمة المرور", self.reset, "secondary"),
                                    button("حذف", self.delete, "danger"), None,
                                    button("تغيير كلمة مروري", self.change_mine, "secondary")))
        self.layout_.addWidget(self.table, 1)

    def on_show(self):
        self.load()

    @guarded
    def load(self):
        rows = []
        for r in self.sv.auth.list_users():
            d = dict(r); d["role_l"] = ROLE_LABELS[d["role"]]; d["active_l"] = "فعال" if d["is_active"] else "موقوف"
            rows.append(d)
        self.table.fill(rows)

    def _role_combo(self, cur="standard"):
        cb = QComboBox()
        for k, v in ROLE_LABELS.items():
            cb.addItem(v, k)
        cb.setCurrentIndex(cb.findData(cur))
        return cb

    @guarded
    def add(self):
        d = FormDialog("مستخدم جديد", self)
        u = d.add("اسم المستخدم:", QLineEdit()); n = d.add("الاسم:", QLineEdit())
        pw, t = password_field(); d.form.addRow("كلمة المرور:", hbox(pw, t))
        role = d.add("نوع الحساب:", self._role_combo())
        if d.exec():
            self.sv.auth.create_user(u.text(), pw.text(), role.currentData(), n.text()); self.load()

    @guarded
    def edit(self):
        r = self.table.current()
        if not r:
            return info(self, "اختر مستخدماً")
        d = FormDialog("تعديل المستخدم", self)
        n = d.add("الاسم:", QLineEdit(r["full_name"]))
        role = d.add("نوع الحساب:", self._role_combo(r["role"]))
        act = d.add("فعال:", QCheckBox()); act.setChecked(bool(r["is_active"]))
        if d.exec():
            self.sv.auth.update_user(r["id"], full_name=n.text(), role=role.currentData(),
                                     is_active=int(act.isChecked()))
            self.load()

    @guarded
    def reset(self):
        r = self.table.current()
        if not r:
            return
        d = FormDialog(f"كلمة مرور جديدة لـ {r['username']}", self)
        pw, t = password_field(); d.form.addRow("كلمة المرور:", hbox(pw, t))
        if d.exec():
            self.sv.auth.reset_password(r["id"], pw.text()); info(self, "تم تغيير كلمة المرور")

    @guarded
    def delete(self):
        r = self.table.current()
        if r and confirm(self, f"حذف المستخدم ({r['username']})؟"):
            self.sv.auth.delete_user(r["id"]); self.load()

    @guarded
    def change_mine(self):
        change_password_dialog(self, self.ctx)


def change_password_dialog(parent, ctx):
    d = FormDialog("تغيير كلمة المرور", parent)
    old, t1 = password_field(); new, t2 = password_field(); new2, t3 = password_field()
    d.form.addRow("الحالية:", hbox(old, t1)); d.form.addRow("الجديدة:", hbox(new, t2))
    d.form.addRow("تأكيد الجديدة:", hbox(new2, t3))
    if d.exec():
        if new.text() != new2.text():
            return info(parent, "كلمتا المرور غير متطابقتين")
        ctx.services.auth.change_own_password(old.text(), new.text())
        info(parent, "تم تغيير كلمة المرور")


class BackupPage(Page):
    title = "النسخ الاحتياطي والاستعادة"
    subtitle = "نسخة كاملة من قاعدة البيانات وأرشيف التوقيعات والأختام والمستندات في ملف واحد."

    def __init__(self, ctx):
        super().__init__(ctx)
        box = QGroupBox("إنشاء نسخة")
        v = QVBoxLayout(box)
        self.arch = QCheckBox("تضمين الأرشيف (الصور والمستندات)"); self.arch.setChecked(True)
        v.addWidget(self.arch)
        v.addLayout(hbox(button("نسخة احتياطية في المجلد الافتراضي", self.backup_default, "accent"),
                         button("نسخة احتياطية في مجلد آخر...", self.backup_to, "secondary"), None))
        self.layout_.addWidget(box)
        self.table = Table([("name", "النسخ المتوفرة"), ("size", "الحجم"), ("path", "المسار")])
        self.layout_.addWidget(self.table, 1)
        self.layout_.addLayout(hbox(button("استعادة النسخة المحددة", self.restore_sel, "danger"),
                                    button("استعادة من ملف...", self.restore_file, "secondary"), None))

    def on_show(self):
        self.load()

    @guarded
    def load(self):
        self.table.fill([{"name": p.name, "size": f"{p.stat().st_size / 1e6:.1f} MB", "path": str(p)}
                         for p in self.sv.backup.list()])

    def _run(self, dest=None):
        run_with_progress(self, "جاري إنشاء النسخة الاحتياطية...", self.sv.backup.create, dest,
                          self.arch.isChecked(), with_progress=False,
                          on_done=lambda p: (self.load(), info(self, f"تم إنشاء النسخة:\n{p}")))

    def backup_default(self):
        self._run()

    def backup_to(self):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد الحفظ")
        if d:
            self._run(d)

    def _restore(self, path):
        if confirm(self, "ستُستبدل البيانات الحالية بمحتوى النسخة (تُحفظ نسخة أمان تلقائياً قبل الاستعادة). متابعة؟"):
            run_with_progress(self, "جاري الاستعادة...", self.sv.backup.restore, path, with_progress=False,
                              on_done=lambda _: info(self, "تمت الاستعادة بنجاح."))

    def restore_sel(self):
        r = self.table.current()
        if r:
            self._restore(r["path"])

    def restore_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "ملف النسخة", "", "SmartAuth backup (*.zip)")
        if f:
            self._restore(f)


class AuditPage(Page):
    title = "سجل العمليات"
    subtitle = "كل عمليات الدخول والإضافة والتعديل والحذف والاستيراد والبحث بالتوقيع."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.table = Table([("at", "الوقت"), ("username", "المستخدم"), ("action", "العملية"),
                            ("target", "الهدف"), ("details", "تفاصيل")])
        self.layout_.addLayout(hbox(button("تحديث", self.on_show, "secondary"), None))
        self.layout_.addWidget(self.table, 1)

    @guarded
    def on_show(self):
        self.table.fill(self.sv.audit.recent(2000))
