"""شاشة تسجيل الدخول وشاشة الإعداد الأول."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QFrame, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from .. import APP_NAME_AR, APP_NAME_EN
from .theme import ACCENT, PRIMARY
from .widgets import button, error


def password_field() -> tuple[QLineEdit, QPushButton]:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.Password)
    t = QPushButton("إظهار")
    t.setProperty("kind", "secondary")
    t.setCheckable(True)
    t.setFixedWidth(80)

    def toggle(on):
        e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        t.setText("إخفاء" if on else "إظهار")
    t.toggled.connect(toggle)
    return e, t


class _Base(QDialog):
    def __init__(self, title):
        super().__init__()
        self.setWindowTitle(title)
        self.setFixedWidth(460)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 16)
        top = QFrame()
        top.setStyleSheet(f"background:{PRIMARY}; border-bottom: 4px solid {ACCENT};")
        tl = QVBoxLayout(top)
        a = QLabel(APP_NAME_AR); a.setStyleSheet("color:white;font-size:15pt;font-weight:bold;")
        b = QLabel(APP_NAME_EN); b.setStyleSheet("color:#C9D6E2;font-size:9pt;")
        for w in (a, b):
            w.setAlignment(Qt.AlignCenter); tl.addWidget(w)
        tl.setContentsMargins(16, 22, 16, 18)
        self.lay.addWidget(top)
        self.form = QFormLayout()
        self.form.setContentsMargins(28, 18, 28, 6)
        self.form.setLabelAlignment(Qt.AlignRight)
        self.lay.addLayout(self.form)
        self.msg = QLabel(""); self.msg.setStyleSheet("color:#B3261E;"); self.msg.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(self.msg)


class LoginDialog(_Base):
    def __init__(self, ctx):
        super().__init__("تسجيل الدخول")
        self.ctx = ctx
        self.user = QLineEdit(); self.user.setPlaceholderText("اسم المستخدم")
        self.pw, toggle = password_field()
        self.pw.setPlaceholderText("كلمة المرور")
        from .widgets import hbox
        self.form.addRow("اسم المستخدم:", self.user)
        self.form.addRow("كلمة المرور:", hbox(self.pw, toggle))
        b = button("دخول", self.do_login)
        b.setDefault(True)
        b.setMinimumHeight(38)
        w = QVBoxLayout(); w.setContentsMargins(28, 4, 28, 0); w.addWidget(b)
        self.lay.addLayout(w)
        self.pw.returnPressed.connect(self.do_login)
        self.user.returnPressed.connect(self.pw.setFocus)
        self.session = None

    def do_login(self):
        try:
            self.session = self.ctx.services.auth.login(self.user.text(), self.pw.text())
            self.accept()
        except Exception as e:  # noqa: BLE001
            self.msg.setText(str(e))
            self.pw.selectAll(); self.pw.setFocus()


class FirstRunDialog(_Base):
    """إنشاء حساب المشغل الرئيسي عند التشغيل الأول."""

    def __init__(self, ctx):
        super().__init__("الإعداد الأول للمنظومة")
        self.ctx = ctx
        note = QLabel("لا توجد حسابات بعد. أنشئ حساب المشغل الرئيسي (Administrator).")
        note.setWordWrap(True)
        self.form.addRow(note)
        self.name = QLineEdit("المشغل الرئيسي")
        self.user = QLineEdit("admin")
        self.pw, t1 = password_field()
        self.pw2, t2 = password_field()
        from .widgets import hbox
        self.form.addRow("الاسم:", self.name)
        self.form.addRow("اسم المستخدم:", self.user)
        self.form.addRow("كلمة المرور:", hbox(self.pw, t1))
        self.form.addRow("تأكيد كلمة المرور:", hbox(self.pw2, t2))
        b = button("إنشاء الحساب", self.create)
        w = QVBoxLayout(); w.setContentsMargins(28, 4, 28, 0); w.addWidget(b)
        self.lay.addLayout(w)

    def create(self):
        if self.pw.text() != self.pw2.text():
            self.msg.setText("كلمتا المرور غير متطابقتين"); return
        if len(self.pw.text()) < 8:
            self.msg.setText("استخدم كلمة مرور لا تقل عن 8 أحرف"); return
        try:
            self.ctx.services.auth.create_initial_admin(self.user.text(), self.pw.text(), self.name.text())
            self.accept()
        except Exception as e:  # noqa: BLE001
            error(self, e)
