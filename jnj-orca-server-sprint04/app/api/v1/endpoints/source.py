from app.models.source import Source
from app.schemas.source import SourceRead, SourceCreate, SourceUpdate
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List 
from app.core.db import get_session
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage


router = APIRouter()


@router.post("/", response_model=SourceRead)
async def create_source(source_in: SourceCreate, db: AsyncSession = Depends(get_session)):
    source = Source.model_validate(source_in)
    
    db.add(source)
    await db.commit()          #  await here
    await db.refresh(source)   #  await here
    
    return source


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(source_id: int, db: AsyncSession = Depends(get_session)):
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/", response_model=CursorPage[SourceRead])
async def get_sources(db: AsyncSession = Depends(get_session)):
    statement = select(Source).order_by(Source.id)
    return await paginate(db, statement)


@router.put("/{source_id}", response_model=SourceRead)
async def update_source(source_id: int, source_in: SourceUpdate, db: AsyncSession = Depends(get_session)):
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = source_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(source, key, value)

    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/{source_id}")
async def delete_source(source_id: int, db: AsyncSession = Depends(get_session)):
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
    return {"ok": True}



