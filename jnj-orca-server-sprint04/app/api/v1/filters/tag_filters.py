from fastapi_filter.contrib.sqlalchemy import Filter
from typing import Optional, List
from app.models import ReportingEffortTag

class TagFilter(Filter):
    tag_name__ilike: Optional[str] = None
    reporting_effort_id__in: Optional[List[int]] = None

    class Constants(Filter.Constants):
        model = ReportingEffortTag
        case_insensitive = True

