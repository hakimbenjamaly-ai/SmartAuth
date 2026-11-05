"""النافذة الرئيسية: واجهة مستقلة لكل نوع حساب، تُبنى حسب الصلاحيات."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import APP_NAME_AR, __version__
from ..core import permissions as P
from .pages.admin import AuditPage, BackupPage, DashboardPage, UsersPage, change_password_dialog
from .pages.entities import EntitiesPage
from .pages.excel import ExcelPage
from .pages.persons import PersonSearchPage
from .pages.review import ReviewPage
from .pages.signature_search import SignatureSearchPage
from .pages.sources import SourcesPage
from .widgets import button


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        s = ctx.session
        self.setWindowTitle(f"{APP_NAME_AR} — {s.full_name or s.username} ({P.ROLE_LABELS[s.role]})")
        self.resize(1400, 860)

        # الصفحات حسب الصلاحية (المستخدم العادي لا تظهر له صفحات Excel أو الإدارة)
        spec = [
            (P.VIEW_AUDIT, "لوحة المعلومات", lambda: DashboardPage(ctx)),
            (P.SEARCH, "البحث عن الأشخاص", lambda: PersonSearchPage(ctx)),
            (P.VIEW_ENTITIES, "البحث عن الجهات", lambda: EntitiesPage(ctx)),
            (P.SEARCH, "البحث برقم الهاتف", lambda: PersonSearchPage(ctx, "phone")),
            (P.SEARCH_SIGNATURE, "البحث باستخدام التوقيع", lambda: SignatureSearchPage(ctx)),
            (P.MANAGE_SOURCES, "إدارة مصادر البيانات", lambda: SourcesPage(ctx)),
            (P.REVIEW_EXTRACTIONS, "مراجعة البيانات المستخرجة", lambda: ReviewPage(ctx)),
            (P.EXCEL_VIEW, "ملفات Excel", lambda: ExcelPage(ctx)),
            (P.MANAGE_USERS, "المستخدمون والصلاحيات", lambda: UsersPage(ctx)),
            (P.BACKUP, "النسخ الاحتياطي", lambda: BackupPage(ctx)),
            (P.VIEW_AUDIT, "سجل العمليات", lambda: AuditPage(ctx)),
        ]
        self.pages = []
        central = QWidget(); h = QHBoxLayout(central); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        side = QWidget(); side.setObjectName("Sidebar"); side.setFixedWidth(250)
        sv = QVBoxLayout(side); sv.setContentsMargins(0, 18, 0, 14)
        t = QLabel(APP_NAME_AR); t.setWordWrap(True); t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:13pt;font-weight:bold;padding:0 12px 6px 12px;")
        sv.addWidget(t)
        u = QLabel(f"{s.full_name or s.username}\n{P.ROLE_LABELS[s.role]}"); u.setAlignment(Qt.AlignCenter)
        u.setStyleSheet("color:#C9D6E2;padding-bottom:12px;")
        sv.addWidget(u)
        self.nav = QListWidget(); self.nav.setObjectName("Nav")
        sv.addWidget(self.nav, 1)
        b1 = button("تغيير كلمة المرور", lambda: change_password_dialog(self, ctx), "secondary")
        b2 = button("تسجيل الخروج", self.logout, "accent")
        for b in (b1, b2):
            w = QHBoxLayout(); w.setContentsMargins(14, 2, 14, 2); w.addWidget(b); sv.addLayout(w)
        v = QLabel(f"الإصدار {__version__} — يعمل دون إنترنت"); v.setAlignment(Qt.AlignCenter)
        v.setStyleSheet("color:#8FA6BA;font-size:8.5pt;padding-top:8px;")
        sv.addWidget(v)
        h.addWidget(side)
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._factories = []
        for perm, label, factory in spec:
            if s.has(perm):
                self.nav.addItem(QListWidgetItem(label))
                self._factories.append(factory)
                self.pages.append(None)
                self.stack.addWidget(QWidget())
        self.nav.currentRowChanged.connect(self.switch)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage("جاهز")

    def switch(self, i: int):
        if i < 0:
            return
        if self.pages[i] is None:  # إنشاء الصفحة عند أول فتح
            page = self._factories[i]()
            old = self.stack.widget(i)
            if old is not None:
                self.stack.removeWidget(old); old.deleteLater()
            self.stack.insertWidget(i, page)
            self.pages[i] = page
        self.stack.setCurrentIndex(i)
        try:
            self.pages[i].on_show()
        except Exception as e:  # noqa: BLE001
            from .widgets import error
            error(self, e)

    def logout(self):
        self.ctx.services.auth.logout()
        self.logout_requested.emit()
        self.close()
