from fastapi_filter.contrib.sqlalchemy import Filter
from typing import List, Optional
from app.models import Study

class StudyFilter(Filter):
    name__ilike: Optional[str] = None
    compound_id__in: Optional[List[int]] = None

    class Constants(Filter.Constants):
        model = Study
        case_insensitive = True

