"""نقطة تشغيل منظومة التصديقات والأرشفة الذكية."""
from __future__ import annotations

import sys
import traceback


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import APP_NAME_AR
    from app.core.context import AppContext
    from app.ui.login import FirstRunDialog, LoginDialog
    from app.ui.main_window import MainWindow
    from app.ui.theme import QSS

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME_AR)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    from PySide6.QtGui import QIcon
    from app.core.config import resource_root
    for ico in (resource_root() / "app.ico", resource_root() / "installer" / "app.ico"):
        if ico.exists():
            app.setWindowIcon(QIcon(str(ico)))
            break

    def excepthook(t, v, tb):
        traceback.print_exception(t, v, tb)
        QMessageBox.critical(None, "خطأ غير متوقع", f"{v}\n\nتم تسجيل التفاصيل في ملف السجل.")
    sys.excepthook = excepthook

    try:
        ctx = AppContext()
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(None, "تعذر فتح قاعدة البيانات", str(e))
        return 1

    if not ctx.services.auth.has_any_user():
        if not FirstRunDialog(ctx).exec():
            return 0

    while True:
        dlg = LoginDialog(ctx)
        if not dlg.exec():
            break
        win = MainWindow(ctx)
        state = {"logout": False}
        win.logout_requested.connect(lambda: state.update(logout=True))
        win.show()
        app.exec()
        if not state["logout"]:
            if ctx.session:
                ctx.services.auth.logout()
            break
    ctx.close()
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from pathlib import Path

        from app.selftest import run
        log = None
        for a in sys.argv:
            if a.startswith("--log="):
                log = Path(a[6:])
        sys.exit(run(log))
    sys.exit(main())
