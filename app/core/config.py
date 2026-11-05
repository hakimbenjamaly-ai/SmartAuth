"""إعدادات المسارات ومجلدات البيانات.

كل البيانات تُحفظ محلياً داخل مجلد البيانات (افتراضياً: %PROGRAMDATA%\\SmartAuth على Windows
أو ~/.smart_auth على الأنظمة الأخرى). يمكن تغييره بمتغير البيئة SMART_AUTH_HOME.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_home() -> Path:
    env = os.environ.get("SMART_AUTH_HOME")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        base = os.environ.get("PROGRAMDATA") or os.path.expanduser("~")
        return Path(base) / "SmartAuth"
    return Path.home() / ".smart_auth"


def resource_root() -> Path:
    """جذر الموارد المرفقة (النماذج، tessdata) سواء عند التشغيل من المصدر أو من PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


@dataclass
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "database" / "smart_auth.db"

    @property
    def signatures(self) -> Path:
        return self.home / "archive" / "signatures"

    @property
    def stamps(self) -> Path:
        return self.home / "archive" / "stamps"

    @property
    def documents(self) -> Path:
        return self.home / "archive" / "documents"

    @property
    def temp(self) -> Path:
        return self.home / "temp"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def models(self) -> Path:
        # نماذج الكتابة اليدوية المحلية (اختيارية) - تُنسخ مع المثبّت
        return resource_root() / "models"

    @property
    def tessdata(self) -> Path:
        return resource_root() / "tessdata"

    def ensure(self) -> "Paths":
        for p in (self.db.parent, self.signatures, self.stamps, self.documents,
                  self.temp, self.backups, self.logs):
            p.mkdir(parents=True, exist_ok=True)
        return self


def get_paths(home: Path | str | None = None) -> Paths:
    return Paths(Path(home) if home else _default_home()).ensure()
