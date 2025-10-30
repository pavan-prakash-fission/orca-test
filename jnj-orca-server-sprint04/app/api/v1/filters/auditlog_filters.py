from fastapi_filter.contrib.sqlalchemy import Filter
from typing import Optional
from app.models import AuditLog


class AuditLogFilter(Filter):
    object_type: Optional[str] = None
    class Constants(Filter.Constants):
        model = AuditLog
        case_insensitive = True
