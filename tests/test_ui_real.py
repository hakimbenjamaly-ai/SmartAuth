"""اختبار الواجهة الحقيقية (PySide6) دون شاشة: بناء كل الصفحات لنوعي الحساب وفتح صفحة بيانات شخص."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    HAVE = "fake_qt" not in sys.modules
except ImportError:
    HAVE = False

pytestmark = pytest.mark.skipif(not HAVE, reason="PySide6 غير مثبت")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    from app.core.context import AppContext
    from app.ui import widgets
    import app.ui.pages.persons as pp

    def _raise(parent, exc, title=""):
        raise exc if isinstance(exc, Exception) else AssertionError(exc)
    monkeypatch.setattr(widgets, "error", _raise)
    monkeypatch.setattr(pp, "error", _raise)
    for name in ("information", "critical", "warning", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    c = AppContext(tmp_path / "h")
    c.services.auth.create_initial_admin("admin", "Admin@123")
    c.services.auth.login("admin", "Admin@123")
    yield c
    c.close()


@pytest.mark.parametrize("role", ["admin", "standard"])
def test_main_window_pages(qapp, ctx, role):
    from app.ui.main_window import MainWindow
    from app.ui.theme import QSS
    qapp.setStyleSheet(QSS)
    pid = ctx.services.persons.add(full_name="تجربة الواجهة", phone="0912345678")
    ctx.services.persons.add_authorization(pid, "2025-01-01", "2030-01-01")
    if role == "standard":
        ctx.services.auth.create_user("u", "User@123", "standard")
        ctx.services.auth.logout(); ctx.services.auth.login("u", "User@123")
    w = MainWindow(ctx)
    w.show()
    n = len(w._factories)
    assert n == (11 if role == "admin" else 4)
    labels = [w.nav.item(i).text() for i in range(n)]
    if role == "standard":
        assert "ملفات Excel" not in labels and "المستخدمون والصلاحيات" not in labels
    for i in range(n):
        w.nav.setCurrentRow(i)
        qapp.processEvents()
        assert w.pages[i] is not None
    # صفحة البحث تعرض الشخص، وصفحة بيانات الشخص تُبنى
    page = w.pages[1]
    assert page.table.rowCount() == 1
    from app.ui.pages.persons import PersonProfileDialog
    d = PersonProfileDialog(ctx, pid, w)
    qapp.processEvents()
    d.close(); w.close()


def test_login_dialog(qapp, ctx):
    from app.ui.login import LoginDialog
    ctx.services.auth.logout()
    d = LoginDialog(ctx)
    d.user.setText("admin"); d.pw.setText("wrong-password")
    d.do_login()
    assert d.session is None and d.msg.text()
    d.pw.setText("Admin@123")
    d.do_login()
    assert d.session is not None and d.session.role == "admin"
