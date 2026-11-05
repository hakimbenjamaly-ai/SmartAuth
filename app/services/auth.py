"""تسجيل الدخول وإدارة المستخدمين."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..core.db import PermissionDenied
from ..core.permissions import MANAGE_USERS, ROLE_PERMS, Session, require
from ..core.security import hash_password, verify_password
from . import BaseService

MAX_FAILED = 5
LOCK_MINUTES = 15


class AuthError(Exception):
    pass


class AuthService(BaseService):
    # اتصال مستقل لقراءة بيانات الاعتماد فقط (لا يمر عبر قيود اتصال الجلسة)
    def _cred_conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.ctx.paths.db)
        c.row_factory = sqlite3.Row
        return c

    def has_any_user(self) -> bool:
        c = self._cred_conn()
        try:
            return c.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        finally:
            c.close()

    def create_initial_admin(self, username: str, password: str, full_name: str = "") -> int:
        """إنشاء حساب المشغل الرئيسي عند أول تشغيل فقط."""
        if self.has_any_user():
            raise PermissionDenied("يوجد مستخدمون مسبقاً؛ لا يمكن إنشاء حساب أولي")
        h = hash_password(password)
        c = self._cred_conn()
        try:
            cur = c.execute(
                "INSERT INTO users(username,password_hash,full_name,role) VALUES (?,?,?, 'admin')",
                (username.strip(), h, full_name or "المشغل الرئيسي"))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()

    def login(self, username: str, password: str) -> Session:
        username = (username or "").strip()
        c = self._cred_conn()
        try:
            row = c.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            if row is None:
                raise AuthError("اسم المستخدم أو كلمة المرور غير صحيحة")
            if not row["is_active"]:
                raise AuthError("هذا الحساب موقوف. يرجى مراجعة المشغل الرئيسي")
            if row["locked_until"] and row["locked_until"] > datetime.now().isoformat(" ", "seconds"):
                raise AuthError("تم قفل الحساب مؤقتاً بسبب محاولات دخول خاطئة متكررة")
            if not verify_password(password, row["password_hash"]):
                failed = row["failed_logins"] + 1
                lock = None
                if failed >= MAX_FAILED:
                    lock = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).isoformat(" ", "seconds")
                    failed = 0
                c.execute("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?",
                          (failed, lock, row["id"]))
                c.commit()
                raise AuthError("اسم المستخدم أو كلمة المرور غير صحيحة")
            c.execute("UPDATE users SET failed_logins=0, locked_until=NULL, "
                      "last_login=datetime('now','localtime') WHERE id=?", (row["id"],))
            c.commit()
        finally:
            c.close()
        s = Session(row["id"], row["username"], row["full_name"], row["role"],
                    ROLE_PERMS[row["role"]])
        self.ctx.set_session(s)
        self.audit("login", f"user:{s.username}")
        return s

    def logout(self) -> None:
        if self.ctx.session:
            self.audit("logout", f"user:{self.ctx.session.username}")
        self.ctx.set_session(None)

    # --------------------------------------------------------- user management
    @require(MANAGE_USERS)
    def list_users(self):
        return self.db.query("SELECT id,username,full_name,role,is_active,created_at,last_login "
                             "FROM users ORDER BY id")

    @require(MANAGE_USERS)
    def create_user(self, username: str, password: str, role: str, full_name: str = "") -> int:
        if role not in ROLE_PERMS:
            raise ValueError("نوع حساب غير معروف")
        if not username.strip():
            raise ValueError("اسم المستخدم مطلوب")
        uid = self.db.insert(
            "INSERT INTO users(username,password_hash,full_name,role) VALUES (?,?,?,?)",
            (username.strip(), hash_password(password), full_name, role))
        self.audit("user_create", f"user:{username}", role)
        return uid

    @require(MANAGE_USERS)
    def update_user(self, user_id: int, *, full_name=None, role=None, is_active=None) -> None:
        if role is not None and role not in ROLE_PERMS:
            raise ValueError("نوع حساب غير معروف")
        if user_id == self.ctx.session.user_id and (role == "standard" or is_active == 0):
            raise ValueError("لا يمكنك تخفيض صلاحياتك أو إيقاف حسابك الحالي")
        if (role == "standard" or is_active == 0) and self._is_last_admin(user_id):
            raise ValueError("يجب أن يبقى مشغل رئيسي واحد فعال على الأقل")
        sets, vals = [], []
        for col, v in (("full_name", full_name), ("role", role), ("is_active", is_active)):
            if v is not None:
                sets.append(f"{col}=?")
                vals.append(v)
        if sets:
            self.db.execute(f"UPDATE users SET {','.join(sets)} WHERE id=?", (*vals, user_id))
            self.audit("user_update", f"user_id:{user_id}", ",".join(sets))

    @require(MANAGE_USERS)
    def reset_password(self, user_id: int, new_password: str) -> None:
        self.db.execute("UPDATE users SET password_hash=?, failed_logins=0, locked_until=NULL WHERE id=?",
                        (hash_password(new_password), user_id))
        self.audit("user_reset_password", f"user_id:{user_id}")

    @require(MANAGE_USERS)
    def delete_user(self, user_id: int) -> None:
        if user_id == self.ctx.session.user_id:
            raise ValueError("لا يمكنك حذف حسابك الحالي")
        if self._is_last_admin(user_id):
            raise ValueError("لا يمكن حذف آخر مشغل رئيسي")
        self.db.execute("DELETE FROM users WHERE id=?", (user_id,))
        self.audit("user_delete", f"user_id:{user_id}")

    def change_own_password(self, old: str, new: str) -> None:
        s = self.ctx.session
        if s is None:
            raise PermissionDenied("يجب تسجيل الدخول أولاً")
        c = self._cred_conn()
        try:
            row = c.execute("SELECT password_hash FROM users WHERE id=?", (s.user_id,)).fetchone()
            if not verify_password(old, row["password_hash"]):
                raise AuthError("كلمة المرور الحالية غير صحيحة")
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), s.user_id))
            c.commit()
        finally:
            c.close()
        self.audit("change_own_password", f"user:{s.username}")

    def _is_last_admin(self, user_id: int) -> bool:
        r = self.db.one("SELECT role,is_active FROM users WHERE id=?", (user_id,))
        if not r or r["role"] != "admin" or not r["is_active"]:
            return False
        n = self.db.scalar("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1")
        return n <= 1
