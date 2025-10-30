from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.api.v1.filters.tag_filters import TagFilter
from fastapi_filter import FilterDepends
from app.core.db import get_session
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogResponse   
from app.api.v1.filters.auditlog_filters import AuditLogFilter


router = APIRouter()



@router.get("/", response_model=CursorPage[AuditLogResponse])
async def list_auditlogs(db: AsyncSession = Depends(get_session),filters: AuditLogFilter = FilterDepends(AuditLogFilter)):
    statement = select(AuditLog).order_by(AuditLog.id)
    statement = filters.filter(statement)
    return await paginate(db, statement)