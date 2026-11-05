"""تعريف الصلاحيات والتحقق منها داخل طبقة الخدمات."""
from __future__ import annotations

import functools
from dataclasses import dataclass, field

from .db import PermissionDenied

# الصلاحيات
VIEW_PERSONS = "view_persons"
VIEW_ENTITIES = "view_entities"
SEARCH = "search"
SEARCH_SIGNATURE = "search_signature"
VIEW_SIGNATURES = "view_signatures"
VIEW_HISTORY = "view_history"
EDIT_DATA = "edit_data"
DELETE_DATA = "delete_data"
MANAGE_ENTITIES = "manage_entities"
MANAGE_SOURCES = "manage_sources"
IMPORT_FILES = "import_files"
REVIEW_EXTRACTIONS = "review_extractions"
EXCEL_VIEW = "excel_view"
EXCEL_EDIT = "excel_edit"
MANAGE_USERS = "manage_users"
BACKUP = "backup"
SETTINGS = "settings"
VIEW_AUDIT = "view_audit"

STANDARD_PERMS = frozenset({VIEW_PERSONS, VIEW_ENTITIES, SEARCH, SEARCH_SIGNATURE,
                            VIEW_SIGNATURES, VIEW_HISTORY})
ADMIN_PERMS = STANDARD_PERMS | frozenset({
    EDIT_DATA, DELETE_DATA, MANAGE_ENTITIES, MANAGE_SOURCES, IMPORT_FILES,
    REVIEW_EXTRACTIONS, EXCEL_VIEW, EXCEL_EDIT, MANAGE_USERS, BACKUP, SETTINGS, VIEW_AUDIT})

ROLE_PERMS = {"admin": ADMIN_PERMS, "standard": STANDARD_PERMS}
ROLE_LABELS = {"admin": "المشغل الرئيسي", "standard": "مستخدم عادي"}


@dataclass
class Session:
    user_id: int
    username: str
    full_name: str
    role: str
    perms: frozenset = field(default_factory=frozenset)

    def has(self, perm: str) -> bool:
        return perm in self.perms


def require(*perms: str):
    """مُزخرف للخدمات: يتحقق من صلاحيات الجلسة الحالية (self.ctx.session)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *a, **kw):
            s = self.ctx.session
            if s is None:
                raise PermissionDenied("يجب تسجيل الدخول أولاً")
            missing = [p for p in perms if not s.has(p)]
            if missing:
                raise PermissionDenied("ليست لديك صلاحية لتنفيذ هذه العملية")
            return fn(self, *a, **kw)
        return wrapper
    return deco
