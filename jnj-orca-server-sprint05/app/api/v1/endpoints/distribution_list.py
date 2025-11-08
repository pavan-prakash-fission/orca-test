from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func
from typing import List, Optional
from app.core.db import get_session
from app.models import DistributionList, DatabaseRelease, Study, Compound
from app.schemas.distribution_list import (
    DistributionListCreate,
    DistributionListResponse,
    DistributionListUpdate
)
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage
from app.utils.authorization import authorize_user
from app.api.v1.filters.output_details_filters import _apply_boolean_filter, _apply_array_boolean_filter
from app.models.database_release_tag import DatabaseReleaseTag
from app.models.associations import DatabaseReleaseTagDistributionListLink

router = APIRouter()


def verify_permission(dl: DistributionList, username: str):
    """Verify if user is owner or co-owner"""
    if dl.created_by != username and username not in (dl.co_owners or []):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to perform this action. Only the owners can modify this User List."
        )


@router.post("/", response_model=DistributionListResponse)
async def create_distribution_list(
    dl: DistributionListCreate,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    """Create a new distribution list"""
    
    # Verify study exists
    study = await db.get(Study, dl.study_id)
    if not study:
        raise HTTPException(
            status_code=404,
            detail=f"Study with id {dl.study_id} not found"
        )
    
    # Check if name already exists in this study
    result = await db.execute(
        select(DistributionList).where(
            DistributionList.name == dl.name,
            DistributionList.study_id == dl.study_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A User List with name '{dl.name}' already exists in this study."
        )

    # Ensure no overlap between co_owners and users
    overlap = set(dl.co_owners or []) & set(dl.users or [])
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"The following users cannot be both owners and members: {', '.join(overlap)}"
        )

    # Create new distribution list
    dl_data = dl.model_dump()
    dl_data["created_by"] = current_user.username

    new_dl = DistributionList(**dl_data)
    db.add(new_dl)
    await db.commit()
    await db.refresh(new_dl)
    return new_dl


@router.get("/", response_model=CursorPage[DistributionListResponse])
async def get_distribution_lists(
    db: AsyncSession = Depends(get_session),
    compound_id: Optional[int] = Query(None, description="Filter by compound ID (lists DLs from all studies in this compound)"),
    study_id: Optional[int] = Query(None, description="Filter by study ID"),
    database_release_id: Optional[int] = Query(None, description="Filter by database release to get study-specific distribution lists"),
    name: Optional[str] = Query(None, description="Filter by distribution list name (supports boolean search)"),
    owners: Optional[str] = Query(None, description="Filter by co-owners (supports boolean search)"),
    reviewers: Optional[str] = Query(None, description="Filter by users/reviewers (supports boolean search)"),
    created_by: Optional[str] = Query(None, description="Filter by created_by username (supports boolean search)"),
    tags: Optional[str] = Query(None, description="Filter by tag names (supports boolean search)")
):
    """
    Get all distribution lists with optional filtering:
    - If compound_id provided: filter by all studies in that compound
    - If study_id provided: filter by study
    - If database_release_id provided: filter by the study of that DBR
    - Combinations validated for data consistency
    - Table-level filters: name, owners (co_owners), reviewers (users), created_by, tags
    - All filters support boolean search operators (AND, OR, NOT) and wildcards (*)
    - If none provided: return all distribution lists
    """
    
    filter_study_ids = None
    
    # CASE 1: compound_id provided (with or without other params)
    if compound_id is not None:
        # Verify compound exists
        compound = await db.get(Compound, compound_id)
        if not compound:
            raise HTTPException(
                status_code=404,
                detail=f"Compound with id {compound_id} not found"
            )
        
        # Get all study IDs for this compound
        result = await db.execute(
            select(Study.id).where(Study.compound_id == compound_id)
        )
        compound_study_ids = result.scalars().all()
        
        # If no studies in compound, return empty list
        if not compound_study_ids:
            filter_study_ids = []
        else:
            # Sub-case 1a: compound_id + study_id + database_release_id
            if study_id is not None and database_release_id is not None:
                # Validate study belongs to compound
                if study_id not in compound_study_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Study {study_id} does not belong to Compound {compound_id}"
                    )
                
                # Validate DBR exists and belongs to study
                dbr = await db.get(DatabaseRelease, database_release_id)
                if not dbr:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Database Release with id {database_release_id} not found"
                    )
                
                if dbr.study_id != study_id:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Database Release {database_release_id} does not belong to Study {study_id}"
                    )
                
                filter_study_ids = [study_id]
            
            # Sub-case 1b: compound_id + database_release_id (no study_id)
            elif database_release_id is not None:
                dbr = await db.get(DatabaseRelease, database_release_id)
                if not dbr:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Database Release with id {database_release_id} not found"
                    )
                
                # Validate DBR's study belongs to compound
                if dbr.study_id not in compound_study_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Database Release {database_release_id} does not belong to any study in Compound {compound_id}"
                    )
                
                filter_study_ids = [dbr.study_id]
            
            # Sub-case 1c: compound_id + study_id (no database_release_id)
            elif study_id is not None:
                if study_id not in compound_study_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Study {study_id} does not belong to Compound {compound_id}"
                    )
                
                filter_study_ids = [study_id]
            
            # Sub-case 1d: Only compound_id (no study_id or database_release_id)
            else:
                filter_study_ids = compound_study_ids
    
    # CASE 2: No compound_id, but study_id and database_release_id provided
    elif study_id is not None and database_release_id is not None:
        dbr = await db.get(DatabaseRelease, database_release_id)
        if not dbr:
            raise HTTPException(
                status_code=404,
                detail=f"Database Release with id {database_release_id} not found"
            )
        
        # Verify that the DBR belongs to the provided study
        if dbr.study_id != study_id:
            raise HTTPException(
                status_code=400,
                detail=f"Database Release {database_release_id} does not belong to Study {study_id}"
            )
        
        filter_study_ids = [study_id]
    
    # CASE 3: Only database_release_id provided
    elif database_release_id is not None:
        dbr = await db.get(DatabaseRelease, database_release_id)
        if not dbr:
            raise HTTPException(
                status_code=404,
                detail=f"Database Release with id {database_release_id} not found"
            )
        filter_study_ids = [dbr.study_id]
    
    # CASE 4: Only study_id provided
    elif study_id is not None:
        study = await db.get(Study, study_id)
        if not study:
            raise HTTPException(
                status_code=404,
                detail=f"Study with id {study_id} not found"
            )
        filter_study_ids = [study_id]
    
    # Create subquery to aggregate tags
    tag_subquery = (
        select(
            DatabaseReleaseTagDistributionListLink.distribution_list_id,
            func.string_agg(DatabaseReleaseTag.tag_name, ',').label('tags')
        )
        .join(
            DatabaseReleaseTag,
            DatabaseReleaseTag.id == DatabaseReleaseTagDistributionListLink.database_release_tag_id
        )
        .group_by(DatabaseReleaseTagDistributionListLink.distribution_list_id)
    ).subquery()
    
    # Build base query - select only DistributionList
    if filter_study_ids is not None:
        if isinstance(filter_study_ids, list):
            if len(filter_study_ids) == 0:
                statement = (
                    select(DistributionList)
                    .outerjoin(tag_subquery, DistributionList.id == tag_subquery.c.distribution_list_id)
                    .where(DistributionList.study_id.in_([]))
                    .order_by(-DistributionList.id)
                )
            else:
                statement = (
                    select(DistributionList)
                    .outerjoin(tag_subquery, DistributionList.id == tag_subquery.c.distribution_list_id)
                    .where(DistributionList.study_id.in_(filter_study_ids))
                    .order_by(-DistributionList.id)
                )
        else:
            statement = (
                select(DistributionList)
                .outerjoin(tag_subquery, DistributionList.id == tag_subquery.c.distribution_list_id)
                .where(DistributionList.study_id == filter_study_ids)
                .order_by(-DistributionList.id)
            )
    else:
        statement = (
            select(DistributionList)
            .outerjoin(tag_subquery, DistributionList.id == tag_subquery.c.distribution_list_id)
            .order_by(-DistributionList.id)
        )
    
    # Apply table-level boolean filters (AND logic)
    if name:
        statement = _apply_boolean_filter(statement, name, DistributionList.name, "name")
    
    if owners:
        statement = _apply_array_boolean_filter(statement, owners, DistributionList.co_owners, "owners")
    
    if reviewers:
        statement = _apply_array_boolean_filter(statement, reviewers, DistributionList.users, "reviewers")
    
    if created_by:
        statement = _apply_boolean_filter(statement, created_by, DistributionList.created_by, "created_by")
    
    if tags:
        statement = _apply_boolean_filter(statement, tags, tag_subquery.c.tags, "tags")
    
    # Add the tags column to selection for fetching but use add_columns
    statement = statement.add_columns(func.coalesce(tag_subquery.c.tags, '').label('tags'))
    
    # Use a custom transformer to handle the tuple results
    
    
    return await paginate(
        db, 
        statement,
        transformer=lambda items: [
            DistributionListResponse(
                **{
                    **{k: v for k, v in row[0].__dict__.items() if not k.startswith('_')},
                    'tags': row[1] if len(row) > 1 else ''
                }
            ) for row in items
        ]
    )


@router.get("/{dl_id}", response_model=DistributionListResponse)
async def get_distribution_list(dl_id: int, db: AsyncSession = Depends(get_session)):
    dl = await db.get(DistributionList, dl_id)
    if not dl:
        raise HTTPException(status_code=404, detail="User List not found")
    return dl


@router.put("/{dl_id}", response_model=DistributionListResponse)
async def update_distribution_list(
    dl_id: int,
    dl_update: DistributionListUpdate,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    """Update a distribution list"""
    
    # Get the distribution list
    dl = await db.get(DistributionList, dl_id)
    if not dl:
        raise HTTPException(
            status_code=404,
            detail="User List not found"
        )
    
    # Check permissions
    verify_permission(dl, current_user.username)

    # If name is being updated, check uniqueness within the study
    if dl_update.name:
        stmt = select(DistributionList).where(
            DistributionList.name == dl_update.name,
            DistributionList.study_id == dl.study_id,
            DistributionList.id != dl_id
        )
        result = await db.execute(stmt)
        existing_dl = result.scalar_one_or_none()

        if existing_dl:
            raise HTTPException(
                status_code=409,
                detail=f"A User List with name '{dl_update.name}' already exists in this study."
            )

    # Get update data
    update_data = dl_update.model_dump(exclude_unset=True)
    
    # Check for overlap between co_owners and users if either is being updated
    new_co_owners = update_data.get('co_owners', dl.co_owners)
    new_users = update_data.get('users', dl.users)
    
    overlap = set(new_co_owners or []) & set(new_users or [])
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"The following users cannot be both owners and members: {', '.join(overlap)}"
        )

    # Add updated_by and updated_at
    update_data["updated_by"] = current_user.username
    update_data["updated_at"] = datetime.now(timezone.utc)

    # Apply updates using SQLModel's update method
    for key, value in update_data.items():
        setattr(dl, key, value)

    db.add(dl)
    await db.commit()
    await db.refresh(dl)
    return dl


@router.delete("/{dl_id}")
async def delete_distribution_list(
    dl_id: int,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    """Delete a distribution list"""
    
    # Get the distribution list
    dl = await db.get(DistributionList, dl_id)
    if not dl:
        raise HTTPException(
            status_code=404,
            detail="User List not found"
        )
    
    # Check permissions
    verify_permission(dl, current_user.username)

    await db.delete(dl)
    await db.commit()
    return {"message": "User List deleted successfully"}