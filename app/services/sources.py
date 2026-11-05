"""إدارة مصادر البيانات (مسارات المجلدات)."""
from __future__ import annotations

import os
from pathlib import Path

from ..core.permissions import MANAGE_SOURCES, require
from . import BaseService

DEFAULT_TYPES = "pdf,jpg,jpeg,png,tif,tiff,bmp,xlsx,xls"


class SourceService(BaseService):
    @require(MANAGE_SOURCES)
    def list(self):
        return self.db.query("""
            SELECT s.*, c.name AS category_name,
                   (SELECT COUNT(*) FROM documents d WHERE d.source_id=s.id) AS docs_count
            FROM data_sources s LEFT JOIN categories c ON c.id=s.category_id ORDER BY s.id""")

    @require(MANAGE_SOURCES)
    def get(self, sid: int):
        return self.db.one("SELECT * FROM data_sources WHERE id=?", (sid,))

    @staticmethod
    def _clean_types(t: str) -> str:
        parts = [p.strip().lower().lstrip(".") for p in (t or DEFAULT_TYPES).replace("؛", ",").split(",")]
        return ",".join(p for p in parts if p)

    @require(MANAGE_SOURCES)
    def add(self, name: str, root_path: str, category_id: int | None, file_types: str = DEFAULT_TYPES,
            recursive: bool = True, is_active: bool = True) -> int:
        if not name.strip() or not root_path.strip():
            raise ValueError("اسم المصدر والمسار مطلوبان")
        i = self.db.insert("INSERT INTO data_sources(name,category_id,root_path,file_types,recursive,is_active) "
                           "VALUES (?,?,?,?,?,?)",
                           (name.strip(), category_id, root_path.strip(), self._clean_types(file_types),
                            int(recursive), int(is_active)))
        self.audit("source_add", f"source:{i}", root_path)
        return i

    @require(MANAGE_SOURCES)
    def update(self, sid: int, **data) -> None:
        allowed = {k: v for k, v in data.items()
                   if k in ("name", "category_id", "root_path", "file_types", "recursive", "is_active")}
        if "file_types" in allowed:
            allowed["file_types"] = self._clean_types(allowed["file_types"])
        if allowed:
            sets = ",".join(f"{k}=?" for k in allowed)
            self.db.execute(f"UPDATE data_sources SET {sets} WHERE id=?", (*allowed.values(), sid))
            self.audit("source_update", f"source:{sid}")

    @require(MANAGE_SOURCES)
    def delete(self, sid: int) -> None:
        self.db.execute("DELETE FROM data_sources WHERE id=?", (sid,))
        self.audit("source_delete", f"source:{sid}")

    @require(MANAGE_SOURCES)
    def check(self, sid: int) -> dict:
        """فحص المسار: الوجود، الصلاحية، عدد الملفات المطابقة، والجديد منها."""
        s = self.get(sid)
        p = Path(s["root_path"])
        info = {"exists": p.exists(), "is_dir": p.is_dir(), "readable": os.access(p, os.R_OK),
                "total": 0, "by_type": {}, "message": ""}
        if not (info["exists"] and info["is_dir"]):
            info["message"] = "المسار غير موجود أو ليس مجلداً"
            return info
        if not info["readable"]:
            info["message"] = "لا توجد صلاحية قراءة على المجلد"
            return info
        for f in self.iter_files(s):
            ext = f.suffix.lower().lstrip(".")
            info["by_type"][ext] = info["by_type"].get(ext, 0) + 1
            info["total"] += 1
        info["message"] = f"المسار صالح: {info['total']} ملف مطابق"
        return info

    @staticmethod
    def iter_files(src):
        exts = {"." + e for e in (src["file_types"] or DEFAULT_TYPES).split(",")}
        root = Path(src["root_path"])
        it = root.rglob("*") if src["recursive"] else root.glob("*")
        for f in it:
            try:
                if f.is_file() and f.suffix.lower() in exts and not f.name.startswith("~$"):
                    yield f
            except OSError:
                continue
