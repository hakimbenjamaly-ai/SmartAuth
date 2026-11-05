"""طبقة الخدمات: كل منطق الأعمال، مع فحص الصلاحيات قبل كل عملية."""
from __future__ import annotations


class Services:
    def __init__(self, ctx):
        from .audit import AuditService
        from .auth import AuthService
        from .backup import BackupService
        from .catalog import CatalogService
        from .excel import ExcelService
        from .ingestion import IngestionService
        from .persons import PersonService
        from .review import ReviewService
        from .signatures import SignatureService
        from .sources import SourceService

        self.audit = AuditService(ctx)
        self.auth = AuthService(ctx)
        self.catalog = CatalogService(ctx)
        self.persons = PersonService(ctx)
        self.signatures = SignatureService(ctx)
        self.sources = SourceService(ctx)
        self.ingestion = IngestionService(ctx)
        self.review = ReviewService(ctx)
        self.excel = ExcelService(ctx)
        self.backup = BackupService(ctx)


class BaseService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def db(self):
        return self.ctx.db

    def audit(self, action: str, target: str = "", details: str = "") -> None:
        s = self.ctx.session
        try:
            self.db.execute(
                "INSERT INTO audit_log(user_id,username,action,target,details) VALUES (?,?,?,?,?)",
                (s.user_id if s else None, s.username if s else None, action, target, details))
        except Exception:  # لا يجب أن يوقف التدقيق العملية
            self.ctx.log.exception("audit failed")
