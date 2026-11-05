"""استيراد الملفات من مصادر البيانات وقراءتها (OCR) واستخراج البيانات للمراجعة."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.permissions import IMPORT_FILES, require
from ..core.security import sha256_file
from ..engine.extract import extract_fields
from ..engine.imaging import imwrite_any
from ..engine.ocr import IMAGE_EXT, PDF_EXT, DocumentReader, find_signature_candidates
from . import BaseService
from .sources import SourceService

Progress = Callable[[int, int, str], None]
EXCEL_EXT = {".xlsx", ".xlsm", ".xls"}


@dataclass
class ScanReport:
    found: int = 0
    new: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    new_ids: list[int] = field(default_factory=list)


class IngestionService(BaseService):
    _reader: DocumentReader | None = None

    @property
    def reader(self) -> DocumentReader:
        if IngestionService._reader is None:
            p = self.ctx.paths
            IngestionService._reader = DocumentReader(models_dir=p.models,
                                                      tessdata_dir=p.tessdata if p.tessdata.exists() else None)
        return IngestionService._reader

    def engine_status(self) -> dict:
        return self.reader.status()

    # ---------------------------------------------------------------- import
    @require(IMPORT_FILES)
    def import_file(self, path: str | Path, source_id: int | None = None) -> tuple[int | None, bool]:
        """يعيد (document_id, is_new). البصمة SHA-256 تمنع استيراد الملف نفسه مرتين."""
        path = Path(path)
        digest = sha256_file(path)
        r = self.db.one("SELECT id FROM documents WHERE sha256=?", (digest,))
        if r:
            return r["id"], False
        ext = path.suffix.lower()
        dest_dir = self.ctx.paths.documents / digest[:2]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{digest}{ext}"
        if not dest.exists():
            shutil.copy2(path, dest)
        did = self.db.insert(
            "INSERT INTO documents(source_id,original_path,archive_path,sha256,file_type,size_bytes) "
            "VALUES (?,?,?,?,?,?)", (source_id, str(path), str(dest), digest, ext.lstrip("."), path.stat().st_size))
        self.audit("document_import", f"document:{did}", str(path))
        return did, True

    @require(IMPORT_FILES)
    def scan_source(self, source_id: int, progress: Progress | None = None) -> ScanReport:
        src = self.db.one("SELECT * FROM data_sources WHERE id=?", (source_id,))
        if not src:
            raise ValueError("مصدر غير موجود")
        if not Path(src["root_path"]).is_dir():
            raise ValueError("المسار غير موجود أو ليس مجلداً")
        files = list(SourceService.iter_files(src))
        rep = ScanReport(found=len(files))
        for i, f in enumerate(files, 1):
            if progress:
                progress(i, len(files), f.name)
            try:
                did, new = self.import_file(f, source_id)
                if new:
                    rep.new += 1
                    rep.new_ids.append(did)
                else:
                    rep.duplicates += 1
            except Exception as e:
                rep.errors.append(f"{f}: {e}")
        self.db.execute("UPDATE data_sources SET last_scan=datetime('now','localtime') WHERE id=?", (source_id,))
        self.audit("source_scan", f"source:{source_id}", f"new={rep.new} dup={rep.duplicates}")
        return rep

    # --------------------------------------------------------------- process
    @require(IMPORT_FILES)
    def process_document(self, doc_id: int) -> dict:
        d = self.db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
        if not d:
            raise ValueError("مستند غير موجود")
        path = Path(d["archive_path"] or d["original_path"])
        ext = path.suffix.lower()
        if ext in EXCEL_EXT:
            self.db.execute("UPDATE documents SET status='processed', ocr_engine='excel', "
                            "processed_at=datetime('now','localtime') WHERE id=?", (doc_id,))
            return {"status": "processed", "fields": 0, "warnings": []}
        if ext not in IMAGE_EXT | PDF_EXT:
            self._finish(doc_id, "failed", "", "", 0, [f"صيغة غير مدعومة: {ext}"])
            return {"status": "failed", "fields": 0, "warnings": [f"صيغة غير مدعومة: {ext}"]}
        self.db.execute("UPDATE documents SET status='processing' WHERE id=?", (doc_id,))
        try:
            res = self.reader.read(path, keep_images=True)
        except Exception as e:
            self.ctx.log.exception("OCR failed")
            self._finish(doc_id, "failed", "", "", 0, [f"فشل قراءة المستند: {e}"])
            return {"status": "failed", "fields": 0, "warnings": [str(e)]}

        self.db.execute("DELETE FROM extractions WHERE document_id=? AND status='pending'", (doc_id,))
        n = 0
        with self.db.transaction():
            for pg in res.pages:
                for f in extract_fields(pg.text, pg.page):
                    self.db.execute("INSERT INTO extractions(document_id,field,value,confidence,page_no) "
                                    "VALUES (?,?,?,?,?)", (doc_id, f.field, f.value, f.confidence, pg.page))
                    n += 1
                # مرشحات التوقيع من الصفحة
                if pg.image is not None:
                    for k, (x, y, w, h) in enumerate(find_signature_candidates(pg.image), 1):
                        crop = pg.image[y:y + h, x:x + w]
                        out = self.ctx.paths.documents / d["sha256"][:2] / f"{d['sha256']}_p{pg.page}_sig{k}.png"
                        imwrite_any(out, crop)
                        self.db.execute("INSERT INTO extractions(document_id,field,value,confidence,page_no) "
                                        "VALUES (?,?,?,?,?)", (doc_id, "signature_candidate", str(out), 0.5, pg.page))
                        n += 1
        expected = {"full_name", "job_title"}
        got = {r["field"] for r in self.db.query("SELECT field FROM extractions WHERE document_id=?", (doc_id,))}
        warnings = list(res.warnings)
        from ..engine.extract import FIELD_LABELS
        if "full_name_en" in got:
            got.add("full_name")
        for m in expected - got:
            warnings.append(f"لم يتمكن البرنامج من قراءة/تحديد: {FIELD_LABELS[m]}")
        status = "processed" if not warnings else ("partial" if res.text.strip() else "failed")
        self._finish(doc_id, status, res.text, "+".join(sorted(res.engines)), res.confidence, warnings)
        self.audit("document_process", f"document:{doc_id}", status)
        return {"status": status, "fields": n, "warnings": warnings}

    def _finish(self, doc_id, status, text, engine, conf, warnings):
        self.db.execute("UPDATE documents SET status=?, ocr_text=?, ocr_engine=?, ocr_confidence=?, warnings=?, "
                        "processed_at=datetime('now','localtime') WHERE id=?",
                        (status, text, engine, conf, json.dumps(warnings, ensure_ascii=False), doc_id))

    @require(IMPORT_FILES)
    def process_pending(self, progress: Progress | None = None, source_id: int | None = None) -> dict:
        q = "SELECT id, original_path FROM documents WHERE status IN ('new','failed')"
        params = ()
        if source_id:
            q += " AND source_id=?"; params = (source_id,)
        rows = self.db.query(q, params)
        summary = {"processed": 0, "partial": 0, "failed": 0}
        for i, r in enumerate(rows, 1):
            if progress:
                progress(i, len(rows), Path(r["original_path"]).name)
            st = self.process_document(r["id"])["status"]
            summary[st] = summary.get(st, 0) + 1
        return summary

    @require(IMPORT_FILES)
    def documents(self, status: str | None = None, source_id: int | None = None, limit: int = 2000):
        where, params = [], []
        if status:
            where.append("d.status=?"); params.append(status)
        if source_id:
            where.append("d.source_id=?"); params.append(source_id)
        q = ("SELECT d.*, s.name AS source_name, "
             "(SELECT COUNT(*) FROM extractions x WHERE x.document_id=d.id AND x.status='pending') AS pending "
             "FROM documents d LEFT JOIN data_sources s ON s.id=d.source_id")
        if where:
            q += " WHERE " + " AND ".join(where)
        return self.db.query(q + " ORDER BY d.id DESC LIMIT ?", (*params, limit))
