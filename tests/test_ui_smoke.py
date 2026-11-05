"""اختبار دخان للواجهة: بناء كل الصفحات لكل نوع حساب واستدعاء on_show مع خدمات حقيقية."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

try:
    import PySide6  # noqa: F401
    REAL_QT = True
except ImportError:
    REAL_QT = False
    import fake_qt
    fake_qt.install()


@pytest.mark.skipif(REAL_QT, reason="يستخدم Qt الوهمي فقط عند غياب PySide6")
@pytest.mark.parametrize("role", ["admin", "standard"])
def test_build_all_pages(tmp_path, role, monkeypatch):
    from app.core.context import AppContext
    from app.ui import widgets
    from app.ui.main_window import MainWindow

    def _raise(parent, exc, title=""):
        raise exc if isinstance(exc, Exception) else AssertionError(exc)
    widgets.error = _raise
    import app.ui.pages.persons as pp
    pp.error = _raise
    ctx = AppContext(tmp_path / "h")
    ctx.services.auth.create_initial_admin("admin", "Admin@123")
    ctx.services.auth.login("admin", "Admin@123")
    ctx.services.persons.add(full_name="تجربة")
    if role == "standard":
        ctx.services.auth.create_user("u", "User@123", "standard")
        ctx.services.auth.logout(); ctx.services.auth.login("u", "User@123")
    w = MainWindow(ctx)
    n = len(w._factories)
    assert n == (11 if role == "admin" else 4)
    for i in range(n):
        w.switch(i)
        assert w.pages[i] is not None
    ctx.close()
