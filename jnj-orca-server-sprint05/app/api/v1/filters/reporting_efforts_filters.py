from fastapi_filter.contrib.sqlalchemy import Filter
from app.models import ReportingEffort
from typing import Optional, List

class ReportingEffortFilter(Filter):
    id: Optional[int] = None
    name__ilike: Optional[str] = None
    database_release_id__in: Optional[List[int]] = None

    class Constants(Filter.Constants):
        model = ReportingEffort
        case_insensitive = True