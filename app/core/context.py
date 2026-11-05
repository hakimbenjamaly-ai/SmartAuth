"""سياق التطبيق: المسارات، قاعدة البيانات، الجلسة الحالية، والخدمات."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Paths, get_paths
from .db import Database
from .permissions import Session


class AppContext:
    def __init__(self, home: Path | str | None = None):
        self.paths: Paths = get_paths(home)
        self.db = Database(self.paths.db)
        self.db.apply_role(None)  # قبل الدخول: صلاحيات القراءة فقط
        self.session: Session | None = None
        self.log = self._setup_log()
        from ..services import Services
        self.services = Services(self)

    def _setup_log(self) -> logging.Logger:
        lg = logging.getLogger("smart_auth")
        if not lg.handlers:
            lg.setLevel(logging.INFO)
            h = RotatingFileHandler(self.paths.logs / "app.log", maxBytes=2_000_000,
                                    backupCount=5, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            lg.addHandler(h)
        return lg

    def set_session(self, session: Session | None) -> None:
        self.session = session
        self.db.apply_role(session.role if session else None)

    def reopen_db(self) -> None:
        """إعادة فتح قاعدة البيانات (بعد الاستعادة من نسخة احتياطية)."""
        role = self.db.role
        self.db.close()
        self.db = Database(self.paths.db)
        self.db.apply_role(role)

    def close(self) -> None:
        self.db.close()
