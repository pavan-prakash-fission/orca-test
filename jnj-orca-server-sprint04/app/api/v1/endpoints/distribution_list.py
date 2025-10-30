from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List
from app.core.db import get_session
from app.models import DistributionList
from app.schemas.distribution_list import DistributionListCreate, DistributionListResponse, DistributionListUpdate
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage
from fastapi import Header
from app.utils.authorization import authorize_user, verify_coowner_permission
from sqlalchemy.orm import selectinload

router = APIRouter()


#  Create
@router.post("/", response_model=DistributionListResponse)
async def create_distribution_list(
    dl: DistributionListCreate, db: AsyncSession = Depends(get_session),current_user=Depends(authorize_user)
):
    #  Check if name already exists
    result = await db.execute(
        select(DistributionList).where(DistributionList.name == dl.name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=[{"field":"name",
                     "message":f"A User List with name '{dl.name}' already exists."}]
        )

    #  Ensure no overlap between co_owners and users
    overlap = set(dl.co_owners or []) & set(dl.users or [])
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=[{"field":"users",
                     "message":f"The following users cannot be both co-owners and members: {', '.join(overlap)}"}]
        )

    #  Create new distribution list
    dl_data = dl.model_dump()
    dl_data["created_by_id"] = current_user.id

    new_dl = DistributionList(**dl_data)
    db.add(new_dl)
    await db.commit()
    await db.refresh(new_dl)
    return new_dl


#  Read all
@router.get("/", response_model=CursorPage[DistributionListResponse])
async def get_distribution_lists(db: AsyncSession = Depends(get_session)):
    statement = select(DistributionList).order_by(-DistributionList.id)
    return await paginate(db, statement)


#  Read by ID
@router.get("/{dl_id}", response_model=DistributionListResponse)
async def get_distribution_list(dl_id: int, db: AsyncSession = Depends(get_session)):
    dl = await db.get(DistributionList, dl_id)
    if not dl:
        raise HTTPException(status_code=404, detail="User List not found")
    return dl


#  Update
@router.put("/{dl_id}", response_model=DistributionListResponse)
async def update_distribution_list(
    dl_id: int, dl_update: DistributionListUpdate, db: AsyncSession = Depends(get_session), x_orca_username: str = Header(..., alias="X-orca-username")
):
    
    result = await db.execute(
    select(DistributionList)
    .options(selectinload(DistributionList.created_by))
    .where(DistributionList.id == dl_id)
    )
    dl = result.scalar_one_or_none()
    if not dl:
        raise HTTPException(status_code=404, 
                            detail=[{"field":"id",
                                    "message":"User List not found"}])
    
    # ✅ Check if the user is a co-owner
    verify_coowner_permission(dl, x_orca_username)

    # Check if "name" is being updated and validate uniqueness
    if dl_update.name:
        stmt = select(DistributionList).where(
            DistributionList.name == dl_update.name,
            DistributionList.id != dl_id  # exclude current record
        )
        result = await db.execute(stmt)
        existing_dl = result.scalar_one_or_none()

        if existing_dl:
            raise HTTPException(
                status_code=409,
                detail=[{"field":"name",
                     "message":f"A User List with name '{dl_update.name}' already exists."}]
            )

    update_data = dl_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dl, key, value)

    db.add(dl)
    await db.commit()
    await db.refresh(dl)
    return dl


#  Delete
@router.delete("/{dl_id}")
async def delete_distribution_list(dl_id: int, db: AsyncSession = Depends(get_session),x_orca_username: str = Header(..., alias="X-orca-username")):
    
    result = await db.execute(
    select(DistributionList)
    .options(selectinload(DistributionList.created_by))
    .where(DistributionList.id == dl_id)
    )
    dl = result.scalar_one_or_none()
    if not dl:
        raise HTTPException(status_code=404,
                            detail=[{"field":"id",
                                    "message":"User List not found"}])
    
    # ✅ Check if the user is a co-owner
    verify_coowner_permission(dl, x_orca_username)

    await db.delete(dl)
    await db.commit()
    return {"message": "User List deleted successfully"}