from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.v1.filters.database_release_filters import DatabaseReleaseFilter
from fastapi_filter import FilterDepends
from app.models.database_release import DatabaseRelease
from app.schemas.database_release import DatabaseReleaseCreate, DatabaseReleaseUpdate, DatabaseReleaseResponse
from app.core.db import get_session
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage

router = APIRouter()

# -------------------
# CREATE
# -------------------
@router.post("/", response_model=DatabaseReleaseResponse)
async def create_database_release(db_release: DatabaseReleaseCreate, db: AsyncSession = Depends(get_session)):
    db_obj = DatabaseRelease.model_validate(db_release)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

# -------------------
# READ (all)
# -------------------
@router.get("/", response_model=CursorPage[DatabaseReleaseResponse])
async def get_database_releases(db: AsyncSession = Depends(get_session),filters: DatabaseReleaseFilter = FilterDepends(DatabaseReleaseFilter)):
    statement = select(DatabaseRelease).order_by(DatabaseRelease.id)
    statement = filters.filter(statement)
    return await paginate(db, statement)


# -------------------
# READ (single)
# -------------------
@router.get("/{db_release_id}", response_model=DatabaseReleaseResponse)
async def get_database_release(db_release_id: int, db: AsyncSession = Depends(get_session)):
    db_release = await db.get(DatabaseRelease, db_release_id)
    if not db_release:
        raise HTTPException(status_code=404, detail="DatabaseRelease not found")
    return db_release

# -------------------
# UPDATE
# -------------------
@router.put("/{db_release_id}", response_model=DatabaseReleaseResponse)
async def update_database_release(db_release_id: int, db_release_update: DatabaseReleaseUpdate, db: AsyncSession = Depends(get_session)):
    db_release = await db.get(DatabaseRelease, db_release_id)
    if not db_release:
        raise HTTPException(status_code=404, detail="DatabaseRelease not found")

    update_data = db_release_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_release, key, value)

    db.add(db_release)
    await db.commit()
    await db.refresh(db_release)
    return db_release

# -------------------
# DELETE
# -------------------
@router.delete("/{db_release_id}")
async def delete_database_release(db_release_id: int, db: AsyncSession = Depends(get_session)):
    db_release = await db.get(DatabaseRelease, db_release_id)
    if not db_release:
        raise HTTPException(status_code=404, detail="DatabaseRelease not found")

    await db.delete(db_release)
    await db.commit()
    return {"ok": True}