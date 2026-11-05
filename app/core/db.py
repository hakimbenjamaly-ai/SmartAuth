"""قاعدة البيانات المحلية SQLite: المخطط، الترحيل، وفرض الصلاحيات على مستوى الاتصال.

الصلاحيات تُفرض في طبقتين:
1. طبقة الخدمات (app.core.permissions.require) قبل تنفيذ أي عملية.
2. طبقة قاعدة البيانات عبر sqlite3 authorizer: اتصال المستخدم العادي لا يستطيع
   تنفيذ INSERT/UPDATE/DELETE على جداول البيانات، ولا قراءة أعمدة كلمات المرور،
   حتى لو تم تجاوز الواجهة أو طبقة الخدمات.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL CHECK (role IN ('admin','standard')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_login    TEXT
);

-- تصنيفات الجهات (قابلة للإدارة، غير مثبتة في الكود)
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS countries (
    id       INTEGER PRIMARY KEY,
    name_ar  TEXT NOT NULL UNIQUE,
    name_en  TEXT,
    iso2     TEXT
);

CREATE TABLE IF NOT EXISTS cities (
    id          INTEGER PRIMARY KEY,
    country_id  INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    UNIQUE (country_id, name)
);

-- الجهات: سفارة، قنصلية، شركة، وزارة، هيئة، مؤسسة...
CREATE TABLE IF NOT EXISTS entities (
    id           INTEGER PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    name         TEXT NOT NULL,
    name_en      TEXT,
    country_id   INTEGER REFERENCES countries(id) ON DELETE SET NULL,
    city_id      INTEGER REFERENCES cities(id) ON DELETE SET NULL,
    address      TEXT,
    phone        TEXT,
    email        TEXT,
    notes        TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (category_id, name)
);
CREATE INDEX IF NOT EXISTS ix_entities_cat ON entities(category_id);

-- الأشخاص المخولون بالتوقيع والتصديق
CREATE TABLE IF NOT EXISTS persons (
    id            INTEGER PRIMARY KEY,
    entity_id     INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    full_name     TEXT NOT NULL,
    full_name_en  TEXT,
    job_title     TEXT,
    phone         TEXT,
    phone_norm    TEXT,
    email         TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_persons_name ON persons(full_name);
CREATE INDEX IF NOT EXISTS ix_persons_phone ON persons(phone_norm);
CREATE INDEX IF NOT EXISTS ix_persons_entity ON persons(entity_id);

-- التفويض وحالته وتواريخ صلاحيته
CREATE TABLE IF NOT EXISTS authorizations (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    entity_id   INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    start_date  TEXT,
    end_date    TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','expired','suspended','revoked')),
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_auth_person ON authorizations(person_id);

-- السجلات التاريخية للتصديقات
CREATE TABLE IF NOT EXISTS certifications (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    entity_id    INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    cert_date    TEXT,
    reference_no TEXT,
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    notes        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_cert_person ON certifications(person_id);

-- صور التوقيعات (الأصل لا يُعدل؛ تُحفظ الخصائص البصرية لتسريع البحث)
CREATE TABLE IF NOT EXISTS signatures (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    image_path   TEXT NOT NULL,
    sha256       TEXT,
    features     BLOB,
    feature_ver  INTEGER,
    is_active    INTEGER NOT NULL DEFAULT 1,
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_sig_person ON signatures(person_id);

CREATE TABLE IF NOT EXISTS stamps (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER REFERENCES persons(id) ON DELETE CASCADE,
    entity_id    INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    image_path   TEXT NOT NULL,
    sha256       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK (person_id IS NOT NULL OR entity_id IS NOT NULL)
);

-- مصادر البيانات (مسارات المجلدات)
CREATE TABLE IF NOT EXISTS data_sources (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    root_path    TEXT NOT NULL,
    file_types   TEXT NOT NULL DEFAULT 'pdf,jpg,jpeg,png,tif,tiff,bmp,xlsx,xls',
    recursive    INTEGER NOT NULL DEFAULT 1,
    is_active    INTEGER NOT NULL DEFAULT 1,
    last_scan    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- المستندات المستوردة (البصمة SHA-256 تمنع التكرار)
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY,
    source_id    INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
    original_path TEXT NOT NULL,
    archive_path TEXT,
    sha256       TEXT NOT NULL UNIQUE,
    file_type    TEXT,
    size_bytes   INTEGER,
    status       TEXT NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new','processing','processed','partial','failed','reviewed')),
    ocr_text     TEXT,
    ocr_engine   TEXT,
    ocr_confidence REAL,
    warnings     TEXT,
    imported_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_docs_status ON documents(status);

-- البيانات المستخرجة بانتظار المراجعة والاعتماد
CREATE TABLE IF NOT EXISTS extractions (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field        TEXT NOT NULL,
    value        TEXT,
    confidence   REAL,
    page_no      INTEGER,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','rejected','edited')),
    reviewed_by  INTEGER REFERENCES users(id),
    reviewed_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_extr_doc ON extractions(document_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER,
    username   TEXT,
    action     TEXT NOT NULL,
    target     TEXT,
    details    TEXT,
    at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""

# بيانات أولية للتصنيفات (تُدرج في قاعدة البيانات فقط، وتدار لاحقاً من الواجهة)
SEED_CATEGORIES = [
    ("LY_EMB_ABROAD", "السفارات الليبية بالخارج", 1),
    ("LY_CONS_ABROAD", "القنصليات الليبية بالخارج", 2),
    ("FOREIGN_EMB_LY", "السفارات الأجنبية في ليبيا", 3),
    ("PUBLIC_CO", "الشركات العامة في ليبيا", 4),
    ("PRIVATE_CO", "الشركات الخاصة في ليبيا", 5),
    ("MINISTRY", "الوزارات", 6),
    ("AUTHORITY", "الهيئات", 7),
    ("INSTITUTION", "المؤسسات", 8),
    ("OTHER", "جهات أخرى", 9),
]

# الجداول التي يُسمح للمستخدم العادي بالكتابة فيها (سجل التدقيق، وآخر دخول فقط)
STANDARD_WRITABLE = {("audit_log", None), ("users", "last_login"), ("users", "failed_logins"),
                     ("users", "locked_until")}
SENSITIVE_COLUMNS = {("users", "password_hash")}


class PermissionDenied(Exception):
    """رفض صلاحية."""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        from .textnorm import normalize_ar, normalize_phone
        self.conn.create_function("norm_ar", 1, normalize_ar, deterministic=True)
        self.conn.create_function("norm_phone", 1, normalize_phone, deterministic=True)
        self.role: str | None = None
        self._migrate()

    # ------------------------------------------------------------------ schema
    def _migrate(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            cur = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'")
            row = cur.fetchone()
            if row is None:
                self.conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                                  (str(SCHEMA_VERSION),))
                self.conn.executemany(
                    "INSERT OR IGNORE INTO categories(code,name,sort_order) VALUES (?,?,?)",
                    SEED_CATEGORIES)
                self.conn.execute(
                    "INSERT OR IGNORE INTO countries(name_ar,name_en,iso2) VALUES ('ليبيا','Libya','LY')")

    # ------------------------------------------------------------- role guard
    def apply_role(self, role: str | None) -> None:
        """تفعيل فرض الصلاحيات على مستوى اتصال قاعدة البيانات."""
        self.role = role
        if role == "admin":
            self.conn.set_authorizer(None)
        else:
            self.conn.set_authorizer(self._standard_authorizer)

    @staticmethod
    def _standard_authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_READ and (arg1, arg2) in SENSITIVE_COLUMNS:
            return sqlite3.SQLITE_IGNORE  # يعاد العمود فارغاً
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE):
            if (arg1, None) in STANDARD_WRITABLE:
                return sqlite3.SQLITE_OK
            if arg1 and arg1.startswith("sqlite_"):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_UPDATE:
            if (arg1, None) in STANDARD_WRITABLE or (arg1, arg2) in STANDARD_WRITABLE:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
                      sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_CREATE_INDEX,
                      sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_CREATE_TRIGGER,
                      sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_ATTACH,
                      sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and arg1 not in (
                "foreign_keys", "journal_mode", "table_info", "user_version", "data_version"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    # ---------------------------------------------------------------- helpers
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self.conn.execute(sql, tuple(params))
            except sqlite3.DatabaseError as e:
                if "not authorized" in str(e).lower():
                    raise PermissionDenied("العملية غير مسموحة لهذا المستخدم (قاعدة البيانات)") from e
                raise

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        r = self.one(sql, params)
        return None if r is None else r[0]

    def insert(self, sql: str, params: Iterable[Any] = ()) -> int:
        return self.execute(sql, params).lastrowid

    @contextmanager
    def transaction(self):
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                yield self
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self.conn.close()
