from __future__ import annotations

from ..core.permissions import VIEW_AUDIT, require
from . import BaseService


class AuditService(BaseService):
    @require(VIEW_AUDIT)
    def recent(self, limit: int = 500):
        return self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
