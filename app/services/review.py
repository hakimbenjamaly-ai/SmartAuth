"""مراجعة البيانات المستخرجة واعتمادها وتحويلها إلى سجلات رسمية."""
from __future__ import annotations

import json

from ..core.permissions import REVIEW_EXTRACTIONS, require
from ..engine.extract import FIELD_LABELS
from . import BaseService


class ReviewService(BaseService):
    @require(REVIEW_EXTRACTIONS)
    def queue(self):
        return self.db.query("""
            SELECT d.id, d.original_path, d.status, d.ocr_confidence, d.warnings, d.processed_at,
                   s.name AS source_name, s.category_id,
                   (SELECT COUNT(*) FROM extractions x WHERE x.document_id=d.id AND x.status='pending') AS pending
            FROM documents d LEFT JOIN data_sources s ON s.id=d.source_id
            WHERE d.status IN ('processed','partial','failed')
              AND (EXISTS (SELECT 1 FROM extractions x WHERE x.document_id=d.id AND x.status='pending')
                   OR d.status IN ('partial','failed'))
            ORDER BY d.id""")

    @require(REVIEW_EXTRACTIONS)
    def document(self, doc_id: int) -> dict:
        d = dict(self.db.one("SELECT d.*, s.category_id FROM documents d "
                             "LEFT JOIN data_sources s ON s.id=d.source_id WHERE d.id=?", (doc_id,)))
        d["warnings"] = json.loads(d["warnings"] or "[]")
        d["extractions"] = [
            {**dict(r), "label": FIELD_LABELS.get(r["field"], "صورة توقيع مقترحة"
                                                  if r["field"] == "signature_candidate" else r["field"])}
            for r in self.db.query("SELECT * FROM extractions WHERE document_id=? ORDER BY page_no, id", (doc_id,))]
        return d

    @require(REVIEW_EXTRACTIONS)
    def edit(self, extraction_id: int, value: str) -> None:
        self.db.execute("UPDATE extractions SET value=?, status='edited', reviewed_by=?, "
                        "reviewed_at=datetime('now','localtime') WHERE id=?",
                        (value, self.ctx.session.user_id, extraction_id))

    @require(REVIEW_EXTRACTIONS)
    def reject(self, extraction_ids: list[int]) -> None:
        for i in extraction_ids:
            self.db.execute("UPDATE extractions SET status='rejected', reviewed_by=?, "
                            "reviewed_at=datetime('now','localtime') WHERE id=?", (self.ctx.session.user_id, i))

    @require(REVIEW_EXTRACTIONS)
    def approve(self, doc_id: int, values: dict, *, entity_id: int | None = None,
                category_id: int | None = None, signature_paths: list[str] | None = None,
                person_id: int | None = None, accepted_ids: list[int] | None = None) -> int:
        """اعتماد مستند: إنشاء/تحديث الشخص، التفويض، سجل التصديق، وأرشفة التوقيعات المختارة.

        values: {full_name, full_name_en, job_title, phone, email, entity, auth_start, auth_end, date, reference_no}
        """
        sv = self.ctx.services
        name = (values.get("full_name") or "").strip()
        if not name and not person_id:
            raise ValueError("يجب تحديد اسم الشخص قبل الاعتماد")
        if entity_id is None and values.get("entity"):
            if not category_id:
                category_id = self.db.scalar("SELECT s.category_id FROM documents d JOIN data_sources s "
                                             "ON s.id=d.source_id WHERE d.id=?", (doc_id,))
            if not category_id:
                category_id = self.db.scalar("SELECT id FROM categories WHERE code='OTHER'")
            entity_id = sv.catalog.find_or_create_entity(values["entity"], category_id)
        pdata = {k: values.get(k) for k in ("full_name", "full_name_en", "job_title", "phone", "email")
                 if values.get(k)}
        if entity_id:
            pdata["entity_id"] = entity_id
        if person_id is None:
            ex = self.db.one("SELECT id FROM persons WHERE norm_ar(full_name)=norm_ar(?) "
                             "AND IFNULL(entity_id,0)=IFNULL(?,0)", (name, entity_id))
            person_id = ex["id"] if ex else None
        if person_id:
            sv.persons.update(person_id, **pdata)
        else:
            person_id = sv.persons.add(**pdata)
        if values.get("auth_start") or values.get("auth_end"):
            sv.persons.add_authorization(person_id, values.get("auth_start"), values.get("auth_end"),
                                         entity_id=entity_id)
        sv.persons.add_certification(person_id, values.get("date"), values.get("reference_no") or "",
                                     entity_id=entity_id, document_id=doc_id)
        for p in signature_paths or []:
            sv.signatures.enroll(person_id, p, source_document_id=doc_id)
        uid = self.ctx.session.user_id
        if accepted_ids is None:
            self.db.execute("UPDATE extractions SET status='approved', reviewed_by=?, "
                            "reviewed_at=datetime('now','localtime') WHERE document_id=? AND status IN ('pending','edited')",
                            (uid, doc_id))
        else:
            for i in accepted_ids:
                self.db.execute("UPDATE extractions SET status='approved', reviewed_by=?, "
                                "reviewed_at=datetime('now','localtime') WHERE id=?", (uid, i))
            self.db.execute("UPDATE extractions SET status='rejected', reviewed_by=? "
                            "WHERE document_id=? AND status='pending'", (uid, doc_id))
        self.db.execute("UPDATE documents SET status='reviewed' WHERE id=?", (doc_id,))
        self.audit("document_approve", f"document:{doc_id}", f"person:{person_id}")
        return person_id
