from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.v1.filters.study_filters import StudyFilter
from fastapi_filter import FilterDepends
from app.models.study import Study
from app.schemas.study import StudyCreate, StudyUpdate, StudyResponse
from app.core.db import get_session
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage

router = APIRouter()

# -------------------
# CREATE
# -------------------
@router.post("/", response_model=StudyResponse)
async def create_study(study: StudyCreate, db: AsyncSession = Depends(get_session)):
    db_study = Study.model_validate(study)
    db.add(db_study)
    await db.commit()
    await db.refresh(db_study)
    return db_study


# -------------------
# READ (all)
# -------------------
@router.get("/", response_model=CursorPage[StudyResponse])
async def get_studies(db: AsyncSession = Depends(get_session),filters: StudyFilter = FilterDepends(StudyFilter)):
    statement = select(Study).order_by(Study.id)
    statement = filters.filter(statement)
    return await paginate(db, statement)



# -------------------
# READ (single)
# -------------------
@router.get("/{study_id}", response_model=StudyResponse)
async def get_study(study_id: int, db: AsyncSession = Depends(get_session)):
    study = await db.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return study


# -------------------
# UPDATE
# -------------------
@router.put("/{study_id}", response_model=StudyResponse)
async def update_study(study_id: int, study_update: StudyUpdate, db: AsyncSession = Depends(get_session)):
    db_study = await db.get(Study, study_id)
    if not db_study:
        raise HTTPException(status_code=404, detail="Study not found")

    study_data = study_update.model_dump(exclude_unset=True)
    for key, value in study_data.items():
        setattr(db_study, key, value)

    db.add(db_study)
    await db.commit()
    await db.refresh(db_study)
    return db_study


# -------------------
# DELETE
# -------------------
@router.delete("/{study_id}")
async def delete_study(study_id: int, db: AsyncSession = Depends(get_session)):
    study = await db.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    await db.delete(study)
    await db.commit()
    return {"ok": True}