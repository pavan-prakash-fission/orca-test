from fastapi_filter.contrib.sqlalchemy import Filter
from typing import Optional
from app.models import Compound


class CompoundFilter(Filter):
    source_id: Optional[int] = None
    name__ilike: Optional[str] = None
    class Constants(Filter.Constants):
        model = Compound
        case_insensitive = True
