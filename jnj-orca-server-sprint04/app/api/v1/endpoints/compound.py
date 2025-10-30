from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.v1.filters.compound_filters import CompoundFilter
from fastapi_filter import FilterDepends
from app.models.compound import Compound
from app.schemas.compound import CompoundCreate, CompoundUpdate, CompoundResponse
from app.core.db import get_session
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage

router = APIRouter()

# -------------------
# CREATE
# -------------------
@router.post("/", response_model=CompoundResponse)
async def create_compound(compound: CompoundCreate, db: AsyncSession = Depends(get_session)):
    db_compound = Compound.model_validate(compound)
    db.add(db_compound)
    await db.commit()
    await db.refresh(db_compound)
    return db_compound


# -------------------
# READ (all)
# -------------------
@router.get("/", response_model=CursorPage[CompoundResponse])
async def get_compounds(db: AsyncSession = Depends(get_session),filters: CompoundFilter = FilterDepends(CompoundFilter)):
    statement = select(Compound).order_by(Compound.id)
    statement = filters.filter(statement)
    return await paginate(db, statement)


# -------------------
# READ (single)
# -------------------
@router.get("/{compound_id}", response_model=CompoundResponse)
async def get_compound(compound_id: int, db: AsyncSession = Depends(get_session)):
    compound = await db.get(Compound, compound_id)
    if not compound:
        raise HTTPException(status_code=404, detail="Compound not found")
    return compound


# -------------------
# UPDATE
# -------------------
@router.put("/{compound_id}", response_model=CompoundResponse)
async def update_compound(compound_id: int, compound_update: CompoundUpdate, db: AsyncSession = Depends(get_session)):
    db_compound = await db.get(Compound, compound_id)
    if not db_compound:
        raise HTTPException(status_code=404, detail="Compound not found")

    compound_data = compound_update.model_dump(exclude_unset=True)
    for key, value in compound_data.items():
        setattr(db_compound, key, value)

    db.add(db_compound)
    await db.commit()
    await db.refresh(db_compound)
    return db_compound


# -------------------
# DELETE
# -------------------
@router.delete("/{compound_id}")
async def delete_compound(compound_id: int, db: AsyncSession = Depends(get_session)):
    compound = await db.get(Compound, compound_id)
    if not compound:
        raise HTTPException(status_code=404, detail="Compound not found")

    await db.delete(compound)
    await db.commit()
    return {"ok": True}