from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.v1.filters.reporting_efforts_filters import ReportingEffortFilter
from fastapi_filter import FilterDepends
from app.models.reporting_effort import ReportingEffort
from app.schemas.reporting_effort import ReportingEffortCreate, ReportingEffortUpdate, ReportingEffortResponse
from app.core.db import get_session
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage

router = APIRouter()

# -------------------
# CREATE
# -------------------
@router.post("/", response_model=ReportingEffortResponse)
async def create_reporting_effort(re: ReportingEffortCreate, db: AsyncSession = Depends(get_session)):
    db_obj = ReportingEffort.model_validate(re)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

# -------------------
# READ (all)
# -------------------
@router.get("/", response_model=CursorPage[ReportingEffortResponse])
async def get_reporting_efforts(db: AsyncSession = Depends(get_session),filters: ReportingEffortFilter = FilterDepends(ReportingEffortFilter)):
    statement = select(ReportingEffort).order_by(ReportingEffort.id)
    statement = filters.filter(statement)
    return await paginate(db, statement)

# -------------------
# READ (single)
# -------------------
@router.get("/{re_id}", response_model=ReportingEffortResponse)
async def get_reporting_effort(re_id: int, db: AsyncSession = Depends(get_session)):
    re = await db.get(ReportingEffort, re_id)
    if not re:
        raise HTTPException(status_code=404, detail="ReportingEffort not found")
    return re

# -------------------
# UPDATE
# -------------------
@router.put("/{re_id}", response_model=ReportingEffortResponse)
async def update_reporting_effort(re_id: int, re_update: ReportingEffortUpdate, db: AsyncSession = Depends(get_session)):
    db_obj = await db.get(ReportingEffort, re_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="ReportingEffort not found")

    update_data = re_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_obj, key, value)

    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

# -------------------
# DELETE
# -------------------
@router.delete("/{re_id}")
async def delete_reporting_effort(re_id: int, db: AsyncSession = Depends(get_session)):
    db_obj = await db.get(ReportingEffort, re_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="ReportingEffort not found")

    await db.delete(db_obj)
    await db.commit()
    return {"ok": True}