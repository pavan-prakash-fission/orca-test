from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from fastapi_filter import FilterDepends
from app.core.db import get_session
from app.models import ReportingEffort, ReportingEffortTag, DatabaseReleaseTag
from app.schemas.tag import BasicReportingEffortTagResponse
from app.schemas.dbr_tag import BasicDatabaseReleaseTagResponse
from app.schemas.combined_tag import CombinedTagResponse
from typing import List
from app.api.v1.filters.dbr_tag_filters import DBRTagFilter
from app.api.v1.filters.tag_filters import TagFilter
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage
from fastapi_pagination.cursor import CursorParams

router = APIRouter()



@router.get("/", response_model=List[CombinedTagResponse])
async def list_combined_tags(
    db: AsyncSession = Depends(get_session),
    re_filters: TagFilter = FilterDepends(TagFilter),
    dbr_filters: DBRTagFilter = FilterDepends(DBRTagFilter),
    params: CursorParams = Depends(),   # injecting params here
):
    dbr_responses: List[BasicDatabaseReleaseTagResponse] = []
    re_responses: CursorPage[BasicReportingEffortTagResponse] | list = []

    if re_filters.reporting_effort_id__in:
        re_stmt = select(ReportingEffortTag).order_by(ReportingEffortTag.id)
        re_stmt = re_filters.filter(re_stmt)
        re_responses = await paginate(db, re_stmt, params)  # passing params

    elif dbr_filters.database_release_id__in:
        dbr_stmt = select(DatabaseReleaseTag).order_by(DatabaseReleaseTag.id)
        dbr_stmt = dbr_filters.filter(dbr_stmt)
        dbr_tags = await db.execute(dbr_stmt)
        dbr_tags = dbr_tags.scalars().all()

        dbr_responses = [
            BasicDatabaseReleaseTagResponse.model_validate(tag, from_attributes=True)
            for tag in dbr_tags
        ]

        re_stmt = (
            select(ReportingEffortTag)
            .join(ReportingEffort, ReportingEffort.id == ReportingEffortTag.reporting_effort_id)
            .where(ReportingEffort.database_release_id.in_(dbr_filters.database_release_id__in))
            .order_by(ReportingEffortTag.id)
        )
        re_responses = await paginate(db, re_stmt, params)  #  passing params

    return [
        CombinedTagResponse(level="DATABASE RELEASE", tags=dbr_responses),
        CombinedTagResponse(level="REPORTING EFFORT", tags=re_responses),
    ]