from fastapi_filter.contrib.sqlalchemy import Filter
from typing import Optional, List
from app.models import DatabaseReleaseTag

class DBRTagFilter(Filter):
    tag_name__ilike: Optional[str] = None
    database_release_id__in: Optional[List[int]] = None

    class Constants(Filter.Constants):
        model = DatabaseReleaseTag
        case_insensitive = True
