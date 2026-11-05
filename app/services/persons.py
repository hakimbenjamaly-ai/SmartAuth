"""الأشخاص المخولون، التفويضات، سجلات التصديق، والأختام."""
from __future__ import annotations

import shutil
import uuid
from datetime import date
from pathlib import Path

from ..core.permissions import (DELETE_DATA, EDIT_DATA, SEARCH, VIEW_HISTORY, VIEW_PERSONS,
                                VIEW_SIGNATURES, require)
from ..core.security import sha256_file
from ..core.textnorm import normalize_ar, normalize_phone
from . import BaseService

PERSON_FIELDS = ("entity_id", "full_name", "full_name_en", "job_title", "phone", "email", "notes")
AUTH_STATUS_LABELS = {"active": "ساري", "expired": "منتهي", "suspended": "موقوف", "revoked": "ملغى"}


def effective_status(status: str, end_date: str | None, today: str | None = None) -> str:
    today = today or date.today().isoformat()
    if status == "active" and end_date and end_date < today:
        return "expired"
    return status


class PersonService(BaseService):
    _SELECT = """
        SELECT p.*, e.name AS entity_name, c.name AS category_name, co.name_ar AS country_name,
               (SELECT a.status FROM authorizations a WHERE a.person_id=p.id
                  ORDER BY IFNULL(a.end_date,'9999') DESC, a.id DESC LIMIT 1) AS auth_status,
               (SELECT a.end_date FROM authorizations a WHERE a.person_id=p.id
                  ORDER BY IFNULL(a.end_date,'9999') DESC, a.id DESC LIMIT 1) AS auth_end,
               (SELECT MAX(cert_date) FROM certifications ce WHERE ce.person_id=p.id) AS last_cert
        FROM persons p
        LEFT JOIN entities e ON e.id=p.entity_id
        LEFT JOIN categories c ON c.id=e.category_id
        LEFT JOIN countries co ON co.id=e.country_id
    """

    # ----------------------------------------------------------------- search
    @require(SEARCH, VIEW_PERSONS)
    def search(self, name: str = "", phone: str = "", entity_id: int | None = None,
               category_id: int | None = None, country_id: int | None = None,
               entity_text: str = "", limit: int = 500):
        where, params = [], []
        if name:
            n = f"%{normalize_ar(name)}%"
            where.append("(norm_ar(p.full_name) LIKE ? OR lower(IFNULL(p.full_name_en,'')) LIKE ? "
                         "OR norm_ar(IFNULL(p.job_title,'')) LIKE ?)")
            params += [n, f"%{name.lower()}%", n]
        if phone:
            ph = normalize_phone(phone)
            # مطابقة جزئية: آخر الأرقام تكفي (مثلاً 912345678)
            tail = ph[-9:] if len(ph) >= 9 else ph
            where.append("p.phone_norm LIKE ?")
            params.append(f"%{tail}%")
        if entity_id:
            where.append("p.entity_id=?"); params.append(entity_id)
        if category_id:
            where.append("e.category_id=?"); params.append(category_id)
        if country_id:
            where.append("e.country_id=?"); params.append(country_id)
        if entity_text:
            where.append("norm_ar(IFNULL(e.name,'')) LIKE ?")
            params.append(f"%{normalize_ar(entity_text)}%")
        q = self._SELECT + (" WHERE " + " AND ".join(where) if where else "")
        rows = self.db.query(q + " ORDER BY p.full_name LIMIT ?", (*params, limit))
        return [self._with_status(r) for r in rows]

    @staticmethod
    def _with_status(r):
        d = dict(r)
        if d.get("auth_status"):
            d["auth_status"] = effective_status(d["auth_status"], d.get("auth_end"))
        d["auth_status_label"] = AUTH_STATUS_LABELS.get(d.get("auth_status") or "", "غير محدد")
        return d

    @require(VIEW_PERSONS)
    def get(self, pid: int) -> dict | None:
        r = self.db.one(self._SELECT + " WHERE p.id=?", (pid,))
        return self._with_status(r) if r else None

    @require(VIEW_PERSONS, VIEW_SIGNATURES, VIEW_HISTORY)
    def profile(self, pid: int) -> dict | None:
        """صفحة بيانات الشخص كاملة."""
        p = self.get(pid)
        if not p:
            return None
        p["signatures"] = [dict(r) for r in self.db.query(
            "SELECT id,image_path,created_at,is_active FROM signatures WHERE person_id=? ORDER BY id", (pid,))]
        p["stamps"] = [dict(r) for r in self.db.query(
            "SELECT id,image_path,created_at FROM stamps WHERE person_id=? "
            "OR (entity_id=? AND person_id IS NULL) ORDER BY id", (pid, p.get("entity_id")))]
        p["authorizations"] = [
            {**dict(r), "effective_status": effective_status(r["status"], r["end_date"]),
             "status_label": AUTH_STATUS_LABELS[effective_status(r["status"], r["end_date"])]}
            for r in self.db.query(
                "SELECT a.*, e.name AS entity_name FROM authorizations a "
                "LEFT JOIN entities e ON e.id=a.entity_id WHERE person_id=? ORDER BY start_date DESC", (pid,))]
        p["certifications"] = [dict(r) for r in self.db.query(
            "SELECT ce.*, e.name AS entity_name FROM certifications ce "
            "LEFT JOIN entities e ON e.id=ce.entity_id WHERE person_id=? ORDER BY cert_date DESC", (pid,))]
        return p

    # ------------------------------------------------------------------- CRUD
    @require(EDIT_DATA)
    def add(self, **data) -> int:
        data = {k: v for k, v in data.items() if k in PERSON_FIELDS}
        if not (data.get("full_name") or "").strip():
            raise ValueError("اسم الشخص مطلوب")
        data["phone_norm"] = normalize_phone(data.get("phone"))
        cols = ",".join(data)
        pid = self.db.insert(f"INSERT INTO persons({cols}) VALUES ({','.join('?' * len(data))})",
                             tuple(data.values()))
        self.audit("person_add", f"person:{pid}", data["full_name"])
        return pid

    @require(EDIT_DATA)
    def update(self, pid: int, **data) -> None:
        data = {k: v for k, v in data.items() if k in PERSON_FIELDS}
        if "phone" in data:
            data["phone_norm"] = normalize_phone(data["phone"])
        if data:
            sets = ",".join(f"{k}=?" for k in data)
            self.db.execute(f"UPDATE persons SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                            (*data.values(), pid))
            self.audit("person_update", f"person:{pid}")

    @require(DELETE_DATA)
    def delete(self, pid: int) -> None:
        # الصور الأصلية تبقى في الأرشيف؛ يحذف السجل فقط
        self.db.execute("DELETE FROM persons WHERE id=?", (pid,))
        self.audit("person_delete", f"person:{pid}")

    # --------------------------------------------------------- authorizations
    @require(EDIT_DATA)
    def add_authorization(self, person_id: int, start_date: str | None, end_date: str | None,
                          status: str = "active", entity_id: int | None = None, notes: str = "") -> int:
        if status not in AUTH_STATUS_LABELS:
            raise ValueError("حالة تفويض غير صحيحة")
        if start_date and end_date and end_date < start_date:
            raise ValueError("تاريخ انتهاء التفويض قبل تاريخ بدايته")
        if entity_id is None:
            entity_id = self.db.scalar("SELECT entity_id FROM persons WHERE id=?", (person_id,))
        i = self.db.insert("INSERT INTO authorizations(person_id,entity_id,start_date,end_date,status,notes) "
                           "VALUES (?,?,?,?,?,?)", (person_id, entity_id, start_date, end_date, status, notes))
        self.audit("authorization_add", f"person:{person_id}", status)
        return i

    @require(EDIT_DATA)
    def update_authorization(self, aid: int, **data) -> None:
        allowed = {k: v for k, v in data.items() if k in ("start_date", "end_date", "status", "notes", "entity_id")}
        if "status" in allowed and allowed["status"] not in AUTH_STATUS_LABELS:
            raise ValueError("حالة تفويض غير صحيحة")
        if allowed:
            sets = ",".join(f"{k}=?" for k in allowed)
            self.db.execute(f"UPDATE authorizations SET {sets} WHERE id=?", (*allowed.values(), aid))
            self.audit("authorization_update", f"authorization:{aid}")

    @require(DELETE_DATA)
    def delete_authorization(self, aid: int) -> None:
        self.db.execute("DELETE FROM authorizations WHERE id=?", (aid,))
        self.audit("authorization_delete", f"authorization:{aid}")

    # ---------------------------------------------------------- certifications
    @require(EDIT_DATA)
    def add_certification(self, person_id: int, cert_date: str | None, reference_no: str = "",
                          entity_id: int | None = None, document_id: int | None = None, notes: str = "") -> int:
        if entity_id is None:
            entity_id = self.db.scalar("SELECT entity_id FROM persons WHERE id=?", (person_id,))
        i = self.db.insert("INSERT INTO certifications(person_id,entity_id,cert_date,reference_no,document_id,notes) "
                           "VALUES (?,?,?,?,?,?)", (person_id, entity_id, cert_date, reference_no, document_id, notes))
        self.audit("certification_add", f"person:{person_id}", cert_date or "")
        return i

    @require(DELETE_DATA)
    def delete_certification(self, cid: int) -> None:
        self.db.execute("DELETE FROM certifications WHERE id=?", (cid,))
        self.audit("certification_delete", f"certification:{cid}")

    # ------------------------------------------------------------------ stamps
    @require(EDIT_DATA)
    def add_stamp(self, image_file: str | Path, person_id: int | None = None,
                  entity_id: int | None = None) -> int:
        src = Path(image_file)
        dest = self.ctx.paths.stamps / f"{uuid.uuid4().hex}{src.suffix.lower() or '.png'}"
        shutil.copy2(src, dest)
        i = self.db.insert("INSERT INTO stamps(person_id,entity_id,image_path,sha256) VALUES (?,?,?,?)",
                           (person_id, entity_id, str(dest), sha256_file(dest)))
        self.audit("stamp_add", f"stamp:{i}")
        return i

    @require(DELETE_DATA)
    def delete_stamp(self, sid: int) -> None:
        self.db.execute("DELETE FROM stamps WHERE id=?", (sid,))
        self.audit("stamp_delete", f"stamp:{sid}")
