from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.api.v1.filters.dbr_tag_filters import DBRTagFilter
from fastapi_filter import FilterDepends
from app.core.db import get_session
from app.models import DatabaseReleaseTag, DistributionList, OutputDetail, OutputDetailVersion, DatabaseRelease, Study, Compound
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
from app.utils.tag_utils import validate_dbr_tag_name_output_conflict,remove_output_details_hstore_tags, update_output_details_hstore_tags, update_tag_name_in_output_versions, clear_draft_status_from_orphan, update_output_draft_status
from app.utils.authorization import authorize_user
from app.utils.enums import RoleEnum
import logging
logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=DatabaseReleaseTagResponse)
async def create_tag(
    tag: DatabaseReleaseTagCreate, session: AsyncSession = Depends(get_session),current_user=Depends(authorize_user)
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
            raise HTTPException(status_code=400, detail="DatabaseRelease not found")
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
                    status_code=400,
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
                    status_code=400,
                    detail=f"OutputDetail IDs not found: {missing_od_ids}"
                )
            # To validate Tag name is not linked with same output in another source
            versions_query = select(OutputDetailVersion).where(
                OutputDetailVersion.output_id.in_(tag.output_ids)
            )

            # Execute base query
            result = await session.execute(versions_query)
            versions = result.scalars().all()

            file_paths = list({
                    "/".join(row.file_path.split("/")[2:-1])
                    for row in versions
            })
            
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
            source_id=db_release.study.compound.source.id  # Set source_id
        )

        session.add(db_tag)

        
        # 1. FLUSH the session to get the db_tag.id
        await session.flush()
        
        # 2️. Fetch is_latest=True versions for each output detail
        result = await session.execute(
            select(OutputDetailVersion)
            .where(
                OutputDetailVersion.output_id.in_([od.id for od in output_detail_objs]),
                OutputDetailVersion.is_latest.is_(True)
            )
        )
        latest_versions = result.scalars().all()

        # 3. Use the new utility function to update OutputDetail tags
        await update_output_details_hstore_tags(
                output_detail_versions=latest_versions,
                tag_id=db_tag.id,
                tag_name=db_tag.tag_name
            )
        
        await session.commit()
        await session.refresh(db_tag)  # reload with relationships
       

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
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=[{
                "field": "tag_name",
                "message": "A tag with this name already exists for the selected database release."
            }]
        )
    except HTTPException:
        # ✅ re-raise custom HTTP errors directly
        raise
    except Exception as e:
        # ✅ Catch-all for unexpected errors
        await session.rollback()
        logger.error(f"Unexpected error in create_tag: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while creating the tag."
        )

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
        
        # fetch with relationships (avoid MissingGreenlet later)
        result = await session.execute(
            select(DatabaseReleaseTag)
            .options(
                selectinload(DatabaseReleaseTag.distribution_lists),
                selectinload(DatabaseReleaseTag.database_release),
            )
            .where(DatabaseReleaseTag.id == tag_id)
        )
        db_tag = result.scalars().first()
        if not db_tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        old_tag_name = db_tag.tag_name
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
                        status_code=400,
                        detail=f"DistributionList IDs not found: {missing}",
                    )
                db_tag.distribution_lists = db_dls


        # update scalar fields
        for key, value in update_data.items():
            setattr(db_tag, key, value)

            session.add(db_tag)
        # call helper if tag_name changed    
        if "tag_name" in update_data and db_tag.tag_name != old_tag_name:
            await update_tag_name_in_output_versions(session, tag_id, db_tag.tag_name)
        await session.commit()
        # refresh with relationships (ensures clean serialization)
        await session.refresh(db_tag)

        return db_tag
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=[{
                "field": "tag_name",
                "message": "A tag with this name already exists for the selected database release."
            }]
        )
    except HTTPException:
        # ✅ re-raise custom HTTP errors directly
        raise
    except Exception as e:
        # ✅ Catch-all for unexpected errors
        await session.rollback()
        logger.error(f"Unexpected error in update_tag: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while updating the tag."
        )


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_session),current_user=Depends(authorize_user)):

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
        
        result = await session.execute(select(DatabaseReleaseTag).where(DatabaseReleaseTag.id == tag_id))
        db_tag = result.scalars().first()
        if not db_tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        # Capture records for HSTORE update
        result = await session.execute(
            select(OutputDetailVersion)
            .where(OutputDetailVersion.tags.has_key(str(tag_id)))
        )
        odv_list = result.scalars().all()
        # Use the utility function to remove the tag entry from HSTORE column
        await remove_output_details_hstore_tags(
            output_detail_versions=odv_list,
            tag_id=tag_id,
        )
        await session.delete(db_tag)
        await session.commit()
        return {"detail": "Tag deleted"}
    except HTTPException:
        # Re-raise known HTTP errors
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        await session.rollback()
        logger.error(f"Unexpected error while deleting tag {tag_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while deleting the tag."
        )


@router.post("/{tag_id}/records", response_model=AddRecordResponse)
async def add_record(
    tag_id: int,
    request_data: AddRecordRequest,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    try:
        # 1️⃣ Validate user
        if current_user.role == RoleEnum.reviewer.value:
            raise HTTPException(
                status_code=403,
                detail=[{
                    "field": "user",
                    "message": "Reviewers are not authorized to create tags."
                }]
            )

        # 2️⃣ Fetch the tag
        result = await session.execute(
            select(DatabaseReleaseTag)
            .options(
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

        # 3️⃣ Fetch valid OutputDetail records
        result = await session.execute(
            select(OutputDetail)
            .where(OutputDetail.id.in_(record_ids))
        )
        valid_records = result.scalars().all()
        valid_ids = {record.id for record in valid_records}

        # 4️⃣ Fetch all OutputDetailVersion entries (no is_latest filter)
        versions_query = select(OutputDetailVersion).where(
            OutputDetailVersion.output_id.in_(valid_ids)
        )

        # Execute base query
        result = await session.execute(versions_query)
        versions = result.scalars().all()

        # 5️⃣ Determine already linked & new records
        already_added_records = []
        new_records = []

        for record in valid_records:
            related_versions = [v for v in versions if v.output_id == record.id]
            is_already_tagged = any(str(tag_id) in (v.tags or {}) for v in related_versions)
            if is_already_tagged:
                already_added_records.append(record.identifier)
            else:
                new_records.append(record)

        added_ids = [r.identifier for r in new_records]

        # 6️⃣ If nothing new to add
        if not new_records:
            return {
                "message": "No new records added to the tag.",
                "tag_name": tag.tag_name,
                "already_added_records": already_added_records,
            }

        # 7️⃣ Validate Tag name not linked with same output in another source
        payload_identifiers = [row.identifier for row in new_records]
        file_paths = list({"/".join(row.file_path.split("/")[2:-1]) for row in versions})

        await validate_dbr_tag_name_output_conflict(
            session=session,
            tag_name=tag.tag_name,
            source_id=tag.database_release.study.compound.source.id,
            payload_identifiers=payload_identifiers,
            database_release_name=tag.database_release.name,
            study_name=tag.database_release.study.name,
            compound_name=tag.database_release.study.compound.name,
            file_paths=file_paths
        )

        # 8️⃣ Update draft flag if needed
        if tag.database_release.study.compound.source.name == "DOCS":
            await update_output_draft_status(
                session=session,
                output_detail_objs=new_records,
                identify_as_draft=request_data.identify_as_draft,
                toggle_mode=False
            )

        # 9️⃣ Update tags (HSTORE field) for OutputDetailVersion
        latest_query = versions_query.where(OutputDetailVersion.is_latest == True)
        latest_result = await session.execute(latest_query)
        latest_versions = latest_result.scalars().all()

        await update_output_details_hstore_tags(
            output_detail_versions=latest_versions,
            tag_id=tag_id,
            tag_name=tag.tag_name
        )
       

        await session.commit()

        return {
            "message": "Records added to tag.",
            "tag_name": tag.tag_name,
            "added_records": added_ids,
            "already_added_records": already_added_records,
        }

    except HTTPException:
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        await session.rollback()
        logger.error(f"Unexpected error while adding record to tag {tag_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while adding records to tag."
        )
    


@router.delete("/{tag_id}/records", response_model=RemoveRecordResponse)
async def remove_record(
    tag_id: int,
    request_data: RemoveRecordRequest,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user),
):
    try:
        # 1️⃣ Validate user
        if current_user.role == RoleEnum.reviewer.value:
            raise HTTPException(
                status_code=403,
                detail=[{
                    "field": "user",
                    "message": "Reviewers are not authorized to remove tags."
                }],
            )

        # 2️⃣ Fetch tag details
        result = await session.execute(
            select(DatabaseReleaseTag).where(DatabaseReleaseTag.id == tag_id)
        )
        tag = result.scalars().first()
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        record_ids = request_data.record_ids

        # 3️⃣ Fetch OutputDetail records for these IDs
        result = await session.execute(
            select(OutputDetail).where(OutputDetail.id.in_(record_ids))
        )
        valid_records = result.scalars().all()
        valid_ids = {od.id for od in valid_records}

        if not valid_records:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "No matching records found for removal.",
                    "not_associated_records": record_ids,
                },
            )

        # 4️⃣ Fetch all OutputDetailVersions for these output details
        result = await session.execute(
            select(OutputDetailVersion).where(OutputDetailVersion.output_id.in_(valid_ids))
        )
        odv_list = result.scalars().all()

        if not odv_list:
            raise HTTPException(
                status_code=404,
                detail="No OutputDetailVersions found for provided record IDs.",
            )


        # Determine which records had tag_id in their tags before removal
        removed_records = []
        not_associated_records = []

        tag_key = str(tag_id)
        for od in valid_records:
            
            tag_found = any(v.tags and tag_key in v.tags for v in odv_list)
            
            if tag_found:
                removed_records.append(od.identifier)
            else:
                not_associated_records.append(od.identifier)

        if not removed_records:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "No records had the specified tag associated.",
                    "not_associated_records": not_associated_records,
                },
            )
        # 5️⃣ Use the utility function to remove the tag entry from HSTORE column
        await remove_output_details_hstore_tags(
            output_detail_versions=odv_list,
            tag_id=tag_id,
        )

        # 6️⃣ Commit changes
        await session.commit()

        # 7️⃣ Optionally clear draft status from orphans
        await clear_draft_status_from_orphan(
            session=session,
            output_detail_ids=list(valid_ids),
        )

        return {
            "message": "Records removed from tag.",
            "tag_id": tag.id,
            "tag_name": tag.tag_name,
            "removed_records": removed_records,
            "not_associated_records": not_associated_records,
        }

    except HTTPException:
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        await session.rollback()
        logger.error(f"Unexpected error while removing records from tag {tag_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while removing records from tag."
        )
        

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
