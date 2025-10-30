from fastapi_filter.contrib.sqlalchemy import Filter
from app.models import DatabaseRelease
from typing import Optional, List

class DatabaseReleaseFilter(Filter):
    id: Optional[int] = None
    name__ilike: Optional[str] = None
    study_id__in: Optional[List[int]] = None

    class Constants(Filter.Constants):
        model = DatabaseRelease
        case_insensitive = True
