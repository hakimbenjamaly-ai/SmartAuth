"""النسخ الاحتياطي والاستعادة لقاعدة البيانات والأرشيف."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .. import __version__
from ..core.permissions import BACKUP, require
from . import BaseService


class BackupService(BaseService):
    @require(BACKUP)
    def create(self, dest_dir: str | Path | None = None, include_archive: bool = True) -> Path:
        dest_dir = Path(dest_dir) if dest_dir else self.ctx.paths.backups
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"SmartAuth_backup_{datetime.now():%Y%m%d_%H%M%S}.zip"
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "smart_auth.db"
            # نسخة متسقة باستخدام SQLite backup API
            src = sqlite3.connect(self.ctx.paths.db)
            dst = sqlite3.connect(snap)
            with dst:
                src.backup(dst)
            src.close(); dst.close()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                z.write(snap, "database/smart_auth.db")
                z.writestr("manifest.json", json.dumps({
                    "app_version": __version__, "created_at": datetime.now().isoformat(),
                    "home": str(self.ctx.paths.home), "include_archive": include_archive}, ensure_ascii=False))
                if include_archive:
                    arch = self.ctx.paths.home / "archive"
                    for f in arch.rglob("*"):
                        if f.is_file():
                            z.write(f, f"archive/{f.relative_to(arch).as_posix()}")
        self.audit("backup_create", str(out))
        return out

    @require(BACKUP)
    def list(self):
        return sorted(self.ctx.paths.backups.glob("SmartAuth_backup_*.zip"), reverse=True)

    @require(BACKUP)
    def restore(self, zip_path: str | Path) -> None:
        """استعادة نسخة: يحفظ نسخة أمان من الوضع الحالي أولاً."""
        zip_path = Path(zip_path)
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            old_home = json.loads(z.read("manifest.json")).get("home", "")
            if "database/smart_auth.db" not in names or "manifest.json" not in names:
                raise ValueError("ملف النسخة الاحتياطية غير صالح")
            for n in names:  # حماية من مسارات خارج المجلد
                if n.startswith("/") or ".." in Path(n).parts:
                    raise ValueError("ملف النسخة يحتوي مسارات غير آمنة")
            safety = self.create(self.ctx.paths.backups / "pre_restore", include_archive=False)
            with tempfile.TemporaryDirectory() as td:
                z.extractall(td)
                tdb = Path(td) / "database" / "smart_auth.db"
                chk = sqlite3.connect(tdb)
                ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
                chk.close()
                if ok != "ok":
                    raise ValueError("قاعدة البيانات في النسخة تالفة")
                # الاستعادة عبر SQLite backup API إلى الاتصال المفتوح (آمن مع WAL)
                srcc = sqlite3.connect(tdb)
                try:
                    with self.ctx.db._lock:
                        srcc.backup(self.ctx.db.conn)
                finally:
                    srcc.close()
                arch_src = Path(td) / "archive"
                if arch_src.exists():
                    arch = self.ctx.paths.home / "archive"
                    for f in arch_src.rglob("*"):
                        if f.is_file():
                            t = arch / f.relative_to(arch_src)
                            t.parent.mkdir(parents=True, exist_ok=True)
                            if t.exists():
                                try:
                                    t.chmod(0o644)
                                except OSError:
                                    pass
                            shutil.copy2(f, t)
        new_home = str(self.ctx.paths.home)
        if old_home and old_home != new_home:  # النسخة من جهاز/مسار آخر: تحديث مسارات الأرشيف
            for tbl, col in (("signatures", "image_path"), ("stamps", "image_path"),
                             ("documents", "archive_path"), ("extractions", "value")):
                self.ctx.db.execute(f"UPDATE {tbl} SET {col}=replace({col},?,?) WHERE {col} LIKE ?",
                                    (old_home, new_home, old_home + "%"))
        self.audit("backup_restore", str(zip_path), f"safety={safety}")
