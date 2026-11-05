"""أرشفة التوقيعات والبحث بالتوقيع."""
from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core.permissions import (DELETE_DATA, EDIT_DATA, SEARCH_SIGNATURE, VIEW_SIGNATURES, require)
from ..core.security import sha256_file
from ..engine import signature as eng
from ..engine.imaging import imread_any, imwrite_any
from . import BaseService
from .persons import AUTH_STATUS_LABELS, effective_status

DEFAULT_THRESHOLD = 0.55   # أقل نسبة تعرض كنتيجة "مشابهة بدرجة كافية"
NOT_FOUND_MSG = "لم يتم العثور على توقيع مطابق أو مشابه بدرجة كافية في قاعدة البيانات."


@dataclass
class SigMatch:
    signature_id: int
    person_id: int
    full_name: str
    job_title: str | None
    entity_name: str | None
    country_name: str | None
    image_path: str
    score: float
    last_cert: str | None
    auth_status: str | None
    auth_status_label: str
    auth_end: str | None

    @property
    def percent(self) -> int:
        return int(round(self.score * 100))


@dataclass
class SigSearchResult:
    query_image: str            # مسار الصورة المؤقتة (لا تسجل كتوقيع رسمي)
    query_preview: str          # معاينة منظفة
    matches: list[SigMatch] = field(default_factory=list)
    searched: int = 0
    elapsed: float = 0.0
    message: str = ""
    disclaimer: str = eng.DISCLAIMER


class SignatureService(BaseService):
    # ------------------------------------------------------------- enrollment
    @require(EDIT_DATA)
    def enroll(self, person_id: int, image_file: str | Path, source_document_id: int | None = None,
               crop: bool = False) -> int:
        """أرشفة صورة توقيع لشخص. الأصل يُنسخ كما هو دون تعديل."""
        src = Path(image_file)
        img = imread_any(src)
        if img is None:
            raise ValueError("تعذر قراءة صورة التوقيع")
        dest = self.ctx.paths.signatures / f"{person_id}_{uuid.uuid4().hex[:12]}{src.suffix.lower() or '.png'}"
        if crop:
            imwrite_any(dest.with_suffix(".png"), eng.cleaned_preview(img))
            dest = dest.with_suffix(".png")
        else:
            shutil.copy2(src, dest)
        try:
            os.chmod(dest, 0o444)  # حماية الأصل من التعديل
        except OSError:
            pass
        feats = eng.compute_features(img)
        sid = self.db.insert(
            "INSERT INTO signatures(person_id,image_path,sha256,features,feature_ver,source_document_id) "
            "VALUES (?,?,?,?,?,?)",
            (person_id, str(dest), sha256_file(dest), feats.to_bytes(), eng.FEATURE_VERSION, source_document_id))
        self.audit("signature_enroll", f"signature:{sid}", f"person:{person_id}")
        return sid

    @require(DELETE_DATA)
    def deactivate(self, sid: int) -> None:
        self.db.execute("UPDATE signatures SET is_active=0 WHERE id=?", (sid,))
        self.audit("signature_deactivate", f"signature:{sid}")

    @require(DELETE_DATA)
    def delete(self, sid: int) -> None:
        self.db.execute("DELETE FROM signatures WHERE id=?", (sid,))
        self.audit("signature_delete", f"signature:{sid}")

    @require(EDIT_DATA)
    def rebuild_features(self) -> int:
        """إعادة حساب خصائص كل التوقيعات (عند تحديث المحرك)."""
        n = 0
        for r in self.db.query("SELECT id,image_path FROM signatures"):
            img = imread_any(r["image_path"])
            if img is None:
                continue
            self.db.execute("UPDATE signatures SET features=?, feature_ver=? WHERE id=?",
                            (eng.compute_features(img).to_bytes(), eng.FEATURE_VERSION, r["id"]))
            n += 1
        self.audit("signature_rebuild", details=str(n))
        return n

    @require(VIEW_SIGNATURES)
    def for_person(self, person_id: int):
        return self.db.query("SELECT * FROM signatures WHERE person_id=? ORDER BY id", (person_id,))

    # ----------------------------------------------------------------- search
    def save_temp_query(self, img: np.ndarray) -> str:
        """حفظ صورة البحث مؤقتاً في مجلد temp (ليست سجلاً رسمياً)."""
        p = self.ctx.paths.temp / f"query_{uuid.uuid4().hex}.png"
        imwrite_any(p, img)
        return str(p)

    def cleanup_temp(self, max_age_hours: float = 12) -> int:
        n, now = 0, time.time()
        for p in self.ctx.paths.temp.glob("query_*"):
            try:
                if now - p.stat().st_mtime > max_age_hours * 3600:
                    p.unlink(); n += 1
            except OSError:
                pass
        return n

    @require(SEARCH_SIGNATURE)
    def search(self, image: str | Path | np.ndarray, category_id: int | None = None,
               country_id: int | None = None, entity_id: int | None = None,
               threshold: float = DEFAULT_THRESHOLD, top_n: int = 20, rerank: bool = True) -> SigSearchResult:
        t0 = time.time()
        img = imread_any(image) if not isinstance(image, np.ndarray) else image
        if img is None:
            raise ValueError("تعذر قراءة صورة التوقيع الممسوح")
        qpath = image if not isinstance(image, np.ndarray) else self.save_temp_query(img)
        prev = self.ctx.paths.temp / f"query_{uuid.uuid4().hex}_clean.png"
        imwrite_any(prev, eng.cleaned_preview(img))
        qf = eng.compute_features(img)

        where, params = ["s.is_active=1"], []
        if category_id:
            where.append("e.category_id=?"); params.append(category_id)
        if country_id:
            where.append("e.country_id=?"); params.append(country_id)
        if entity_id:
            where.append("p.entity_id=?"); params.append(entity_id)
        rows = self.db.query(f"""
            SELECT s.id AS sid, s.image_path, s.features, s.feature_ver, p.id AS pid, p.full_name,
                   p.job_title, e.name AS entity_name, co.name_ar AS country_name,
                   (SELECT MAX(cert_date) FROM certifications c WHERE c.person_id=p.id) AS last_cert,
                   (SELECT a.status FROM authorizations a WHERE a.person_id=p.id
                      ORDER BY IFNULL(a.end_date,'9999') DESC, a.id DESC LIMIT 1) AS auth_status,
                   (SELECT a.end_date FROM authorizations a WHERE a.person_id=p.id
                      ORDER BY IFNULL(a.end_date,'9999') DESC, a.id DESC LIMIT 1) AS auth_end
            FROM signatures s JOIN persons p ON p.id=s.person_id
            LEFT JOIN entities e ON e.id=p.entity_id
            LEFT JOIN countries co ON co.id=e.country_id
            WHERE {' AND '.join(where)}""", params)

        scored = []
        for r in rows:
            f = eng.SigFeatures.from_bytes(r["features"]) if r["features"] else None
            if f is None:  # خصائص قديمة/مفقودة: تحسب من الصورة
                im = imread_any(r["image_path"])
                if im is None:
                    continue
                f = eng.compute_features(im)
            scored.append((eng.similarity(qf, f), r))
        scored.sort(key=lambda t: t[0], reverse=True)

        if rerank and scored:
            head = scored[:max(top_n, 10)]
            new = []
            for s, r in head:
                im = imread_any(r["image_path"])
                o = eng.orb_score(img, im) if im is not None else 0.0
                # تطابق نقاط ORB يرفع الترتيب، وضعفه يخفض النسبة قليلاً فقط
                new.append((s * (0.9 + 0.1 * min(1.0, o / 0.3)), r))
            new.sort(key=lambda t: t[0], reverse=True)
            scored = new + scored[len(head):]

        # أفضل نتيجة لكل شخص
        best: dict[int, SigMatch] = {}
        for s, r in scored:
            if s < threshold or r["pid"] in best:
                continue
            st = effective_status(r["auth_status"], r["auth_end"]) if r["auth_status"] else None
            best[r["pid"]] = SigMatch(r["sid"], r["pid"], r["full_name"], r["job_title"], r["entity_name"],
                                      r["country_name"], r["image_path"], s, r["last_cert"], st,
                                      AUTH_STATUS_LABELS.get(st or "", "غير محدد"), r["auth_end"])
        matches = list(best.values())[:top_n]
        res = SigSearchResult(str(qpath), str(prev), matches, len(rows), time.time() - t0)
        if not matches:
            res.message = NOT_FOUND_MSG
        self.audit("signature_search", details=f"candidates={len(rows)} matches={len(matches)}")
        return res
