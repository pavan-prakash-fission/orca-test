from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.api.v1.filters.dbr_tag_filters import DBRTagFilter
from fastapi_filter import FilterDepends
from app.core.db import get_session
from app.models import DatabaseReleaseTag, DistributionList, OutputDetail, DatabaseRelease, Study, Compound
from app.schemas.dbr_tag import (
    
    AddRecordResponse,
    DatabaseReleaseTagCreate,
    DatabaseReleaseTagResponse,
    DatabaseReleaseTagUpdate,
    AddRecordRequest,
    RemoveRecordRequest,
    RemoveRecordResponse,
)
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage
from app.utils.validate_tag_output_conflict import validate_dbr_tag_name_output_conflict
from app.utils.update_output_draft_status import clear_draft_status_from_orphan, update_output_draft_status
from app.utils.authorization import authorize_user
from app.utils.enums import RoleEnum
from app.utils.update_output_details_tags import remove_output_details_hstore_tags, update_output_details_hstore_tags

router = APIRouter()


@router.post("/", response_model=DatabaseReleaseTagResponse)
async def create_tag(
    tag: DatabaseReleaseTagCreate, session: AsyncSession = Depends(get_session),current_user=Depends(authorize_user)
):
    # Validate user
    if current_user.role == RoleEnum.reviewer.value:
        raise HTTPException(
            status_code=403,
            detail=[{
                "field": "user",
                "message": "Reviewers are not authorized to create tags."
            }]
        )
    
    #  Validate DatabaseRelease
    # db_release = await session.get(DatabaseRelease, tag.database_release_id)
    db_release = await session.get(
        DatabaseRelease,
        tag.database_release_id,
        options=[
            selectinload(DatabaseRelease.study)
            .selectinload(Study.compound)
            .selectinload(Compound.source)
        ],
    )
    if not db_release:
        raise HTTPException(status_code=404, detail="DatabaseRelease not found")
    #  Validate Distribution Lists
    distribution_list_objs: List[DistributionList] = []
    if tag.distribution_list_ids:
        result = await session.execute(
            select(DistributionList).where(DistributionList.id.in_(tag.distribution_list_ids))
        )
        distribution_list_objs = result.scalars().all()
        missing_dl_ids = set(tag.distribution_list_ids) - {dl.id for dl in distribution_list_objs}
        if missing_dl_ids:
            raise HTTPException(
                status_code=404,
                detail=f"DistributionList IDs not found: {missing_dl_ids}"
            )

    #  Validate OutputDetails
    output_detail_objs: List[OutputDetail] = []
    if tag.output_ids:
        result = await session.execute(
            select(OutputDetail) 
            .where(OutputDetail.id.in_(tag.output_ids))
        )
        output_detail_objs = result.scalars().all()
        missing_od_ids = set(tag.output_ids) - {od.id for od in output_detail_objs}
        payload_identifiers = [row.identifier for row in output_detail_objs]
        if missing_od_ids:
            raise HTTPException(
                status_code=404,
                detail=f"OutputDetail IDs not found: {missing_od_ids}"
            )
        # To validate Tag name is not linked with same output in another source
        file_paths = [
                "/".join(row.file_path.split("/")[2:-1])
                for row in output_detail_objs
            ]
        
        await validate_dbr_tag_name_output_conflict(session=session,
                            tag_name=tag.tag_name,
                            source_id=db_release.study.compound.source.id,
                            payload_identifiers=payload_identifiers,
                            database_release_name=db_release.name,
                            study_name=db_release.study.name,
                            compound_name=db_release.study.compound.name,
                            file_paths=file_paths
                            )

        # Update OutputDetail based on draft flag
        if db_release.study.compound.source.name == "DOCS":
            
            await update_output_draft_status(
                    session=session,
                    output_detail_objs=output_detail_objs,
                    identify_as_draft=tag.identify_as_draft,
                    toggle_mode=False
                )
           

    # Create DatabaseReleaseTag
    db_tag = DatabaseReleaseTag(
        database_release_id=tag.database_release_id,
        tag_name=tag.tag_name,
        reason=tag.reason,
        users=tag.users or [],
        distribution_lists=distribution_list_objs,
        output_details=output_detail_objs,
        source_id=db_release.study.compound.source.id  # Set source_id
    )

    session.add(db_tag)

    try:
        # 1. FLUSH the session to get the db_tag.id
        await session.flush()

        # 2. Use the new utility function to update OutputDetail tags
        await update_output_details_hstore_tags(
                output_detail_objs=output_detail_objs,
                tag_id=db_tag.id,
                tag_name=db_tag.tag_name
            )
        
        await session.commit()
        await session.refresh(db_tag)  # reload with relationships
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=[{"field":"tag_name",
                     "message":"A tag with this name already exists for the selected database release."}]
        )

    #  Fetch tag with relationships for response
    result = await session.execute(
        select(DatabaseReleaseTag)
        .options(
            selectinload(DatabaseReleaseTag.distribution_lists),
            selectinload(DatabaseReleaseTag.output_details),
        )
        .where(DatabaseReleaseTag.id == db_tag.id)
    )
    db_tag_with_rel = result.scalars().first()
    return db_tag_with_rel

@router.get("/{tag_id}", response_model=DatabaseReleaseTagResponse)
async def get_tag(tag_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(DatabaseReleaseTag)
        .options(
            selectinload(DatabaseReleaseTag.distribution_lists),
            selectinload(DatabaseReleaseTag.output_details),
        )
        .where(DatabaseReleaseTag.id == tag_id)
    )
    db_tag = result.scalars().first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return db_tag



@router.get("/", response_model=CursorPage[DatabaseReleaseTagResponse])
async def list_tags(
    db: AsyncSession = Depends(get_session),
    filters: DBRTagFilter = FilterDepends(DBRTagFilter),
    current_user=Depends(authorize_user),
    tagged_data: bool = Query(False)
):
    base_stmt = select(DatabaseReleaseTag).order_by(-DatabaseReleaseTag.id)

    if current_user.role == RoleEnum.reviewer.value and tagged_data:
        user_to_search = current_user.username
        if not user_to_search:
            raise HTTPException(status_code=400, detail="username is required for reviewers")
        stmt = select(DatabaseReleaseTag).where(DatabaseReleaseTag.users.any(user_to_search)).order_by(-DatabaseReleaseTag.id)
        return await paginate(db, stmt)

    stmt = filters.filter(base_stmt)
    return await paginate(db, stmt) 


@router.put("/{tag_id}", response_model=DatabaseReleaseTagResponse)
async def update_tag(
    tag_id: int,
    tag: DatabaseReleaseTagUpdate,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    # Validate user
    if current_user.role == RoleEnum.reviewer.value:
        raise HTTPException(
            status_code=403,
            detail=[{
                "field": "user",
                "message": "Reviewers are not authorized to create tags."
            }]
        )
    
    # fetch with relationships (avoid MissingGreenlet later)
    result = await session.execute(
        select(DatabaseReleaseTag)
        .options(
            selectinload(DatabaseReleaseTag.distribution_lists),
            selectinload(DatabaseReleaseTag.output_details),
            selectinload(DatabaseReleaseTag.database_release),
        )
        .where(DatabaseReleaseTag.id == tag_id)
    )
    db_tag = result.scalars().first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    update_data = tag.model_dump(exclude_unset=True)

    # handle distribution list updates
    if "distribution_list_ids" in update_data:
        dl_ids = update_data.pop("distribution_list_ids")
        if dl_ids is not None:
            result = await session.execute(
                select(DistributionList).where(DistributionList.id.in_(dl_ids))
            )
            db_dls = result.scalars().all()
            missing = set(dl_ids) - {dl.id for dl in db_dls}
            if missing:
                raise HTTPException(
                    status_code=404,
                    detail=f"DistributionList IDs not found: {missing}",
                )
            db_tag.distribution_lists = db_dls

    # handle output details updates
    if "output_ids" in update_data:
        od_ids = update_data.pop("output_ids")
        if od_ids is not None:
            result = await session.execute(
                select(OutputDetail).where(OutputDetail.id.in_(od_ids))
            )
            db_ods = result.scalars().all()
            missing = set(od_ids) - {od.id for od in db_ods}
            if missing:
                raise HTTPException(
                    status_code=404,
                    detail=f"OutputDetail IDs not found: {missing}",
                )
            
            db_tag.output_details = db_ods

    # update scalar fields
    for key, value in update_data.items():
        setattr(db_tag, key, value)

    session.add(db_tag)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=[{"field":"tag_name",
                     "message":"A tag with this name already exists for the selected database release."}]
        )

    # refresh with relationships (ensures clean serialization)
    await session.refresh(db_tag)

    return db_tag


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_session),current_user=Depends(authorize_user)):

    # Validate user
    if current_user.role == RoleEnum.reviewer.value:
        raise HTTPException(
            status_code=403,
            detail=[{
                "field": "user",
                "message": "Reviewers are not authorized to create tags."
            }]
        )
    
    # result = await session.execute(select(DatabaseReleaseTag).where(DatabaseReleaseTag.id == tag_id))
    result = await session.execute(
        select(DatabaseReleaseTag)
        .options(selectinload(DatabaseReleaseTag.output_details))
        .where(DatabaseReleaseTag.id == tag_id)
    )
    db_tag = result.scalars().first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Capture records for HSTORE update
    records_to_update = list(db_tag.output_details)
    # 2. Use the utility function to remove the tag entry from HSTORE column
    await remove_output_details_hstore_tags(
        output_detail_objs=records_to_update,
        tag_id=tag_id,
    )
    await session.delete(db_tag)
    await session.commit()
    return {"detail": "Tag deleted"}

@router.post("/{tag_id}/records", response_model=AddRecordResponse)
async def add_record(
    tag_id: int,
    request_data: AddRecordRequest,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    try:
        # Validate user
        if current_user.role == RoleEnum.reviewer.value:
            raise HTTPException(
                status_code=403,
                detail=[{
                    "field": "user",
                    "message": "Reviewers are not authorized to create tags."
                }]
            )
    
        # Fetch tag instance with relationship (to avoid MissingGreenlet)
        result = await session.execute(
            select(DatabaseReleaseTag)
            .options(
            selectinload(DatabaseReleaseTag.output_details),
            selectinload(DatabaseReleaseTag.database_release)
                .selectinload(DatabaseRelease.study)
                .selectinload(Study.compound)
                .selectinload(Compound.source)
            )
            .where(DatabaseReleaseTag.id == tag_id)
        )
        tag = result.scalars().first()
        
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")
        
        record_ids = request_data.record_ids

        # Fetch valid records
        result = await session.execute(
            select(OutputDetail)
            .where(OutputDetail.id.in_(record_ids))
        )
        valid_records = result.scalars().all()
        valid_ids = {record.id for record in valid_records}

        # Already linked records
        already_added_records = [
            od.identifier for od in tag.output_details if od.id in valid_ids
        ]

        # New records to add
        existing_ids = {od.id for od in tag.output_details}
        new_records = [record for record in valid_records if record.id not in existing_ids]
        added_ids = [record.identifier for record in new_records]

        if not new_records:
            return {
                "message": "No new records added to the tag.",
                "tag_name": tag.tag_name,
                "already_added_records": already_added_records,
            }
        
        # To validate Tag name is not linked with same output in another source
        payload_identifiers = [row.identifier for row in new_records]
        
        file_paths = [
                "/".join(row.file_path.split("/")[2:-1])
                for row in new_records
            ]
       
        await validate_dbr_tag_name_output_conflict(session=session,
                            tag_name=tag.tag_name,
                            source_id=tag.database_release.study.compound.source.id,
                            payload_identifiers=payload_identifiers,
                            database_release_name=tag.database_release.name,
                            study_name=tag.database_release.study.name,
                            compound_name=tag.database_release.study.compound.name,
                            file_paths=file_paths
                            )
        
        # Update OutputDetail based on draft flag
        if tag.database_release.study.compound.source.name == "DOCS":
            
            await update_output_draft_status(
                    session=session,
                    output_detail_objs=new_records,
                    identify_as_draft=request_data.identify_as_draft,
                    toggle_mode=False
                )
        
        # 🔑 Use the new utility function to update OutputDetail tags for new records
        await update_output_details_hstore_tags(
            output_detail_objs=new_records,
            tag_id=tag_id,
            tag_name=tag.tag_name
        )
        # Add records
        tag.output_details.extend(new_records)
        session.add(tag)
        await session.commit()
        await session.refresh(tag)

        return {
            "message": "Records added to tag.",
            "tag_name": tag.tag_name,
            "added_records": added_ids,
            "already_added_records": already_added_records,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
    

@router.delete("/{tag_id}/records", response_model=RemoveRecordResponse)
async def remove_record(
    tag_id: int,
    request_data: RemoveRecordRequest,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    try:
        # Validate user
        if current_user.role == RoleEnum.reviewer.value:
            raise HTTPException(
                status_code=403,
                detail=[{
                    "field": "user",
                    "message": "Reviewers are not authorized to create tags."
                }]
            )
        # Fetch tag instance with relationship eager loaded
        result = await session.execute(
            select(DatabaseReleaseTag)
            .options(selectinload(DatabaseReleaseTag.output_details))
            .where(DatabaseReleaseTag.id == tag_id)
        )
        tag = result.scalars().first()

        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        record_ids = request_data.record_ids

        # Records currently associated with the tag
        valid_records = [od for od in tag.output_details if od.id in record_ids]
        valid_ids = {od.id for od in valid_records}
        removed_ids = [od.identifier for od in valid_records]

        # IDs not associated
        not_associated_records = set(record_ids) - valid_ids

        if not valid_records:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "No matching records found for removal.",
                    "not_associated_records": list(not_associated_records),
                },
            )

        # 🔑 NEW: Remove tag from HSTORE column for the records being unlinked
        await remove_output_details_hstore_tags(
            output_detail_objs=valid_records,
            tag_id=tag_id,
        )
        
        # Remove valid records
        for record in valid_records:
            tag.output_details.remove(record)

        session.add(tag)
        await session.commit()
        await session.refresh(tag)

        await clear_draft_status_from_orphan(
            session=session,
            output_detail_ids=list(valid_ids))

        return {
            "message": "Records removed from tag.",
            "tag_id": tag.id,
            "tag_name": tag.tag_name,
            "removed_records": removed_ids,
            "not_associated_records": list(not_associated_records),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
    

@router.post("/{tag_id}/users")
async def add_users_to_tag(
    tag_id: int,
    usernames: str,  # comma-separated usernames
    db: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
    
):
    # Validate user
    if current_user.role == RoleEnum.reviewer.value:
        raise HTTPException(
            status_code=403,
            detail=[{
                "field": "user",
                "message": "Reviewers are not authorized to create tags."
            }]
        )
    
    # 1. Fetch tag
    result = await db.execute(select(DatabaseReleaseTag).where(DatabaseReleaseTag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # 2. Parse usernames
    usernames_list = [u.strip() for u in usernames.split(",") if u.strip()]
    if not usernames_list:
        raise HTTPException(status_code=400, detail="No valid usernames provided")
    
    # 3. Ensure no duplicates
    existing_users = set(tag.users or [])
    new_users = [u for u in usernames_list if u not in existing_users]
    
    if not new_users:
        return {"message": "No new users added", "users": tag.users}

    # 4. Update tag
    # tag.users.extend(new_users)
    tag.users = tag.users + new_users
    
    try:
        db.add(tag)
        await db.commit()
        await db.refresh(tag)
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating tag: {str(e)}")

    return {"message": "Users added to tag", "users": tag.users}

@router.delete("/{tag_id}/users")
async def remove_users_from_tag(
    tag_id: int,
    usernames: str,  # comma-separated usernames
    db: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    # Validate user
    if current_user.role == RoleEnum.reviewer.value:
        raise HTTPException(
            status_code=403,
            detail=[{
                "field": "user",
                "message": "Reviewers are not authorized to create tags."
            }]
        )
    
    # 1. Fetch tag
    result = await db.execute(
        select(DatabaseReleaseTag).where(DatabaseReleaseTag.id == tag_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # 2. Parse usernames
    usernames_list = [u.strip() for u in usernames.split(",") if u.strip()]
    if not usernames_list:
        raise HTTPException(status_code=400, detail="No valid usernames provided")

    existing_users = set(tag.users or [])
    to_remove = [u for u in usernames_list if u in existing_users]
    not_found = [u for u in usernames_list if u not in existing_users]

    if not to_remove:
        return {
            "message": "No matching users found for removal",
            "tag_id": tag.id,
            "users": tag.users,
            "not_found": not_found,
        }

    # 3. Update users list
    tag.users = [u for u in tag.users if u not in to_remove]

    try:
        db.add(tag)
        await db.commit()
        await db.refresh(tag)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating tag: {str(e)}")

    return {
        "message": "Users removed from tag",
        "tag_id": tag.id,
        "removed_users": to_remove,
        "remaining_users": tag.users,
        "not_found": not_found,
    }
