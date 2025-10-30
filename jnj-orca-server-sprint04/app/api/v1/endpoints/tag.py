from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.api.v1.filters.tag_filters import TagFilter
from fastapi_filter import FilterDepends
from app.core.db import get_session
from app.models import ReportingEffortTag, DistributionList, OutputDetail, ReportingEffort, DatabaseRelease, Study, Compound
from app.schemas.tag import (
    AddRecordResponse,
    RecordRequest,
    RemoveRecordResponse,
    ReportingEffortTagCreate,
    ReportingEffortTagUpdate,
    ReportingEffortTagResponse,
)
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.cursor import CursorPage
from app.utils.validate_tag_output_conflict import validate_re_tag_name_output_conflict

router = APIRouter()


@router.post("/", response_model=ReportingEffortTagResponse)
async def create_tag(tag: ReportingEffortTagCreate, session: AsyncSession = Depends(get_session)):
    #validate reporting effort
    re = await session.get(
        ReportingEffort,
        tag.reporting_effort_id,
        options=[
            selectinload(ReportingEffort.database_release)
            .selectinload(DatabaseRelease.study)
            .selectinload(Study.compound)
            .selectinload(Compound.source)
        ],
    )
    if not re:
        raise HTTPException(status_code=404, detail="ReportingEffort not found")
    # validate distribution lists
    distribution_list_objs = []
    if tag.distribution_list_ids:
        result = await session.execute(
            select(DistributionList).where(DistributionList.id.in_(tag.distribution_list_ids))
        )
        distribution_list_objs = result.scalars().all()
        missing = set(tag.distribution_list_ids) - {dl.id for dl in distribution_list_objs}
        if missing:
            raise HTTPException(status_code=404, detail=f"DistributionList IDs not found: {missing}")

    # validate output details
    output_detail_objs = []
    if tag.output_ids:
        result = await session.execute(
            select(OutputDetail).where(OutputDetail.id.in_(tag.output_ids))
        )
        output_detail_objs = result.scalars().all()
        missing_ids = set(tag.output_ids) - {od.id for od in output_detail_objs}
        payload_identifiers = [row.identifier for row in output_detail_objs]
        
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"OutputDetail IDs not found: {missing_ids}")
        
        await validate_re_tag_name_output_conflict(session=session,
                            tag_name=tag.tag_name,
                            source_id=re.database_release.study.compound.source.id,
                            payload_identifiers=payload_identifiers,
                            reporting_effort_name=re.name,
                            database_release_name=re.database_release.name,
                            study_name=re.database_release.study.name,
                            compound_name=re.database_release.study.compound.name
                            )
        
    # create tag
    db_tag = ReportingEffortTag(
        reporting_effort_id=tag.reporting_effort_id,
        tag_name=tag.tag_name,
        users=tag.users,
        reason=tag.reason,
        distribution_lists=distribution_list_objs,
        output_details=output_detail_objs,
        source_id=re.database_release.study.compound.source.id
    )
    
    session.add(db_tag)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=[{"field":"tag_name",
                     "message":"A tag with this name already exists for the selected reporting effort."}]
        )
    await session.refresh(db_tag)
    # re-fetch with relationships loaded
    result = await session.execute(
        select(ReportingEffortTag)
        .options(
            selectinload(ReportingEffortTag.distribution_lists),
            selectinload(ReportingEffortTag.output_details),
        )
        .where(ReportingEffortTag.id == db_tag.id)
    )
    return result.scalars().first()


@router.get("/{tag_id}", response_model=ReportingEffortTagResponse)
async def get_tag(tag_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ReportingEffortTag)
        .options(
            selectinload(ReportingEffortTag.distribution_lists),
            selectinload(ReportingEffortTag.output_details),
        )
        .where(ReportingEffortTag.id == tag_id)
    )
    db_tag = result.scalars().first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return db_tag



@router.get("/", response_model=CursorPage[ReportingEffortTagResponse])
async def list_tags(db: AsyncSession = Depends(get_session),filters: TagFilter = FilterDepends(TagFilter)):
    statement = select(ReportingEffortTag).order_by(-ReportingEffortTag.id)
    statement = filters.filter(statement)
    return await paginate(db, statement)
   


@router.put("/{tag_id}", response_model=ReportingEffortTagResponse)
async def update_tag(
    tag_id: int,
    tag: ReportingEffortTagUpdate,
    session: AsyncSession = Depends(get_session),
):
    # fetch with relationships (avoid MissingGreenlet later)
    result = await session.execute(
        select(ReportingEffortTag)
        .options(
            selectinload(ReportingEffortTag.distribution_lists),
            selectinload(ReportingEffortTag.output_details),
            selectinload(ReportingEffortTag.reporting_effort),
        )
        .where(ReportingEffortTag.id == tag_id)
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
                     "message":"A tag with this name already exists for the selected reporting effort."}]
        )

    # refresh with relationships (ensures clean serialization)
    await session.refresh(db_tag)

    return db_tag


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ReportingEffortTag).where(ReportingEffortTag.id == tag_id))
    db_tag = result.scalars().first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    await session.delete(db_tag)
    await session.commit()
    return {"detail": "Tag deleted"}

@router.post("/{tag_id}/records", response_model=AddRecordResponse)
async def add_record(
    tag_id: int,
    request_data: RecordRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        # Fetch tag instance with relationship (to avoid MissingGreenlet)
        result = await session.execute(
            select(ReportingEffortTag)
            .options(
                # eager load relationships
                selectinload(ReportingEffortTag.output_details)
            )
            .where(ReportingEffortTag.id == tag_id)
        )
        tag = result.scalars().first()

        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")
        
        record_ids = request_data.record_ids

        # Fetch valid records
        result = await session.execute(
            select(OutputDetail).where(OutputDetail.id.in_(record_ids))
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
    request_data: RecordRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        # Fetch tag instance with relationship eager loaded
        result = await session.execute(
            select(ReportingEffortTag)
            .options(selectinload(ReportingEffortTag.output_details))
            .where(ReportingEffortTag.id == tag_id)
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

        # Remove valid records
        for record in valid_records:
            tag.output_details.remove(record)

        session.add(tag)
        await session.commit()
        await session.refresh(tag)

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
    db: AsyncSession = Depends(get_session)
    
):
    # 1. Fetch tag
    result = await db.execute(select(ReportingEffortTag).where(ReportingEffortTag.id == tag_id))
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
):
    # 1. Fetch tag
    result = await db.execute(
        select(ReportingEffortTag).where(ReportingEffortTag.id == tag_id)
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