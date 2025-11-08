"""
    API endpoints for CRUD operations and paginated retrieval of OutputDetails.
    Includes support for filtering, tag aggregation,
    and special handling for "preprod" source.
    API endpoints for managing OutputDetail resources.

    This module provides CRUD operations for OutputDetails,

    Endpoints:
    - POST /: Create a new OutputDetail.
    - GET /: Retrieve paginated OutputDetail records with optional filters.
    - GET /{output_detail_id}: Retrieve a single OutputDetail by its ID.
    - PUT /{output_detail_id}: Update an existing OutputDetail by its ID.
    - DELETE /{output_detail_id}: Delete an OutputDetail by its ID.

    Tag filtering and boolean search are supported for text fields and tags.
    Special handling is included for "preprod" source filtering.
"""
import mimetypes
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi_filter import FilterDepends
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlmodel import paginate
from sqlalchemy import case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import func, select
from app.core.db import get_session
from app.models import OutputDetail, Source, OutputDetailVersion
from app.utils.tag_utils import remove_output_details_hstore_tags, update_output_details_hstore_tags, update_output_draft_status
from app.schemas.output_detail import (
    OutputDetailCreate,
    OutputDetailRead,
    OutputDetailUpdate,
    OutputDetailWithTags,
    OutputDetailSyncRequest,
    OutputDetailDeleteRequest,
    UpdateDraftStatusRequest,
    BulkUpdateRequest
)
from app.api.v1.filters.output_details_filters import (
    OutputDetailFilter,
    apply_filter
)
from app.utils.authorization import authorize_user
from app.utils.get_user_output_mapping import get_user_to_output_mapping, get_reviewer_accessible_output_ids_query
from app.utils.s3_boto_client import generate_presigned_url
from app.utils.deletion_of_outputs import delete_outputs_and_cleanup
from app.utils.lustre_sync_module import update_multiple_versions_to_s3
from app.models import Compound, Study, DatabaseRelease, DatabaseReleaseTag, ReportingEffort
from app.utils.authorize_reviewer import authorize_reviewer
from sqlalchemy.orm import attributes

router = APIRouter()


@router.post("/", response_model=OutputDetailRead)
async def create_output_detail(
    output_detail: OutputDetailCreate,
    session: AsyncSession = Depends(get_session)
) -> OutputDetailRead:
    """
        Creates a new OutputDetail record in the database.
        Args:
            output_detail (OutputDetailCreate):
                The data required to create a new OutputDetail.
            session (AsyncSession, optional):
                The database session dependency.
        Returns:
            OutputDetail: The newly created OutputDetail instance.
    """
    db_output_detail = OutputDetail(**output_detail.model_dump())
    session.add(db_output_detail)
    await session.commit()
    await session.refresh(db_output_detail)
    return db_output_detail


@router.get("/", response_model=CursorPage[OutputDetailWithTags])
async def read_output_details(
    params: CursorParams = Depends(),
    session: AsyncSession = Depends(get_session),
    filters: OutputDetailFilter = FilterDepends(OutputDetailFilter),
    current_user=Depends(authorize_user)
) -> CursorPage[OutputDetailWithTags]:
    """
        Retrieve paginated OutputDetail records with optional filters applied.
        Supports boolean search for text fields and tag arrays.
        Role-based access control:
        - Programmers: see all outputs
        - Reviewers: see only outputs they have tag-based access to
        
        Args:
            params (CursorParams, optional):
                Pagination parameters.
            session (AsyncSession, optional):
                Database session dependency.
            filters (OutputDetailFilter, optional):
                Filters to apply to the query.
            username (str, optional):
                Username from X-orca-username header.
                
        Returns:
            CursorPage[OutputDetailWithTags]:
                Paginated OutputDetail records with tags.
                
        Raises:
            HTTPException: If any filter is invalid.
    """
    version_expr = func.concat(
        OutputDetailVersion.version_major, '.',
        OutputDetailVersion.version_minor, '.',
        OutputDetailVersion.version_patch
    )
    stmt = (
        select(
            OutputDetail.id.label("id"),
            OutputDetail.identifier.label("identifier"),
            func.concat(
                OutputDetail.title,
                " - [",
                case(
                    (OutputDetail.reporting_effort_id.isnot(None), "Reporting Effort"),
                    (OutputDetail.database_release_id.isnot(None), "Database Release"),
                    (OutputDetail.study_id.isnot(None), "Study"),
                    (OutputDetail.compound_id.isnot(None), "Compound"),
                    else_="General"
                ),
                "]"
            ).label("title"),
            OutputDetail.created_at.label("created_at"),
            OutputDetailVersion.file_path.label("file_path"),
            OutputDetailVersion.file_size.label("file_size"),
            OutputDetail.file_type.label("file_type"),
            case(
                (OutputDetailVersion.is_latest.is_(True), False),
                else_=True
            ).label("is_out_of_sync"),
            OutputDetail.reporting_effort_id.label("reporting_effort_id"),
            OutputDetail.database_release_id.label("database_release_id"),
            OutputDetail.study_id.label("study_id"),
            OutputDetail.compound_id.label("compound_id"),
            OutputDetail.source_id.label("source_id"),
            OutputDetail.source_name.label("source"),
            version_expr.label("version"),
            func.coalesce(OutputDetail.reporting_effort_name, 'NA').label("reporting_effort"),
            func.coalesce(OutputDetail.database_release_name, 'NA').label("database_release"),
            func.coalesce(OutputDetail.study_name, 'NA').label("study"),
            func.coalesce(OutputDetail.compound_name, 'NA').label("compound"),
            case(
                (OutputDetail.docs_shared_as == "PREPROD", "Yes"),
                else_=""
            ).label("docs_shared_as"),
            func.coalesce(func.avals(OutputDetailVersion.tags), []).label("reporting_effort_tags"),
            func.coalesce(func.akeys(OutputDetailVersion.tags), []).label("tag_ids")
        )
        .join(OutputDetailVersion, OutputDetailVersion.output_id == OutputDetail.id)
    )
    preprod_source_id = await session.scalar(
        select(Source.id).where(Source.name.ilike("preprod"))
    )
    # Dynamically switch to latest version and tagged Version

    if (
        preprod_source_id
        and filters.source_id == preprod_source_id
        and current_user.role.lower() == "reviewer"
    ):
        stmt = stmt.where(OutputDetail.tags != None)

    # NEW: Role-based access control
    # if current_user.role.lower() == "reviewer":
    #     # For reviewers, get all output IDs they have access to
    #     accessible_output_ids = await get_reviewer_accessible_output_ids_query(
    #         session, current_user.username
    #     )
        
    #     if not accessible_output_ids:
    #         # Reviewer has no access to any outputs - return empty result
    #         # Create an impossible condition to return empty set
    #         stmt = stmt.where(OutputDetail.id.in_([]))
    #     else:
    #         # Filter to only outputs the reviewer has access to
    #         stmt = stmt.where(OutputDetail.id.in_(accessible_output_ids))
    
    # If user_role is "programmer" or None, no additional filtering (show all)


    # Apply all filters, including tag boolean search

    if filters.tag_id__in is None:
        # Only fetch latest versions if tag ids are not selected
        stmt = stmt.where(OutputDetailVersion.is_latest.is_(True))

    stmt = await apply_filter(
        session=session,
        stmt=stmt,
        filters=filters,
    )
    if stmt is None:
        return CursorPage.create([], params=params, total=0)
    stmt = stmt.order_by(OutputDetail.id)
    return await paginate(session, stmt, params)

@router.get("/reviewers/tags/combinations")
async def read_reviewer_tagged_output_details(
    tag_name: str,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    """
        Retrieve OutputDetail records for reviewers based on a specific tag.
        Args:
            tag_name (str): The tag name to filter OutputDetails.
            session (AsyncSession): Database session dependency.
            username (str): Username from X-orca-username header.
        Returns:
            JSON with nested combinations including database_release_tag_id:
    """
    try:
        tag = (tag_name or "").strip()
        if not tag:
            return JSONResponse(status_code=400, content={"detail": "tag_name is required"})

        tag_lower = tag.lower()

        # Select distinct combinations of compound -> study -> database_release -> reporting_effort
        # and include the matching database_release_tag.id (as tag_id) for the provided tag_name.
        stmt = (
            select(
                Compound.id.label("compound_id"),
                Compound.name.label("compound_name"),
                Study.id.label("study_id"),
                Study.name.label("study_name"),
                DatabaseRelease.id.label("database_release_id"),
                DatabaseRelease.name.label("database_release_name"),
                DatabaseReleaseTag.id.label("database_release_tag_id"),
                ReportingEffort.id.label("reporting_effort_id"),
                ReportingEffort.name.label("reporting_effort_name"),
            )
            .select_from(OutputDetail)
            .join(ReportingEffort, ReportingEffort.id == OutputDetail.reporting_effort_id)
            .join(DatabaseRelease, DatabaseRelease.id == ReportingEffort.database_release_id)
            .join(Study, Study.id == DatabaseRelease.study_id)
            .join(Compound, Compound.id == Study.compound_id)
            .join(
                DatabaseReleaseTag,
                DatabaseReleaseTag.database_release_id == DatabaseRelease.id
            )
            .where(func.lower(DatabaseReleaseTag.tag_name) == tag_lower)
            .distinct()
            .order_by(Compound.name, Study.name, DatabaseRelease.name, ReportingEffort.name)
        )

        result = await session.execute(stmt)
        rows = result.all()

        # Use dicts to deduplicate and maintain relationships
        compounds = {}
        studies = {}
        db_releases = {}
        reporting_efforts = {}

        for row in rows:
            # Compounds
            compounds[row.compound_id] = {
                "compound_id": str(row.compound_id),
                "compound_name": row.compound_name
            }

            # Studies (include compound_id)
            studies[row.study_id] = {
                "study_id": str(row.study_id),
                "study_name": row.study_name,
                "compound_id": str(row.compound_id)
            }

            # Database releases (include study_id)
            db_releases[row.database_release_id] = {
                "database_release_id": str(row.database_release_id),
                "database_release_name": row.database_release_name,
                "study_id": str(row.study_id)
            }

            # Reporting efforts (include database_release_id and tag_id)
            reporting_efforts[row.reporting_effort_id] = {
                "reporting_effort_id": str(row.reporting_effort_id),
                "reporting_effort_name": row.reporting_effort_name,
                "database_release_id": str(row.database_release_id),
                "tag_id": str(row.database_release_tag_id) if row.database_release_tag_id is not None else None
            }

        # Convert maps to lists
        compounds = list(compounds.values())
        studies = list(studies.values())
        database_releases = list(db_releases.values())
        reporting_efforts = list(reporting_efforts.values())

        return JSONResponse(
            status_code=200,
            content={
            "compounds": compounds,
            "studies": studies,
            "database_releases": database_releases,
            "reporting_efforts": reporting_efforts
            }
        )
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Server error: {str(e)}"
        ) from e


@router.get("/{output_detail_id}", response_model=OutputDetailRead)
async def read_output_detail(
        output_detail_id: int,
        session: AsyncSession = Depends(get_session)
        ) -> OutputDetailRead:
    """
        Retrieve an OutputDetail record by its ID.

        Args:
            output_detail_id (int): The ID of the OutputDetail to retrieve.
            session (AsyncSession, optional): Database session dependency.

        Raises:
            HTTPException: If the OutputDetail with the given ID is not found.

        Returns:
            OutputDetail: The OutputDetail record matching the provided ID.
    """
    result = await session.execute(
        select(OutputDetail).where(OutputDetail.id == output_detail_id)
    )
    db_output_detail = result.scalars().first()
    if not db_output_detail:
        raise HTTPException(status_code=404, detail="Output detail not found")
    return db_output_detail


@router.post("/sync")
async def sync_output_details(
    output_ids: OutputDetailSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Synchronize the is_out_of_sync status of multiple OutputDetail records .
    Args:
        output_ids (OutputDetailSyncRequest):
            A list of OutputDetail IDs to synchronize.
        session (AsyncSession, optional):
            The database session dependency.
    Raises:
        HTTPException:
            If no IDs are provided or if a database error occurs.
    Returns:
        JSONResponse:
            A confirmation message indicating the synchronization status.

    """

    try:
        if output_ids.output_detail_ids:
            result = await session.execute(
                select(OutputDetailVersion).where(
                    OutputDetailVersion.output_id.in_(output_ids.output_detail_ids),
                    OutputDetailVersion.tags.has_key(str(output_ids.tag_id))
                )
            )
            output_version_details = result.scalars().all()
            output_detail_ids = output_ids.output_detail_ids
        else:
            result = await session.execute(
                select(OutputDetailVersion).where(
                    OutputDetailVersion.tags.has_key(str(output_ids.tag_id))
                )
            )
            output_version_details = result.scalars().all()
            output_detail_ids = list({odv.output_id for odv in output_version_details})
        
        # Removing existing tag details in tags Hstore
        await remove_output_details_hstore_tags(
        output_detail_versions=output_version_details,
        tag_id=output_ids.tag_id,
        )
        
        # Adding tag details to latest version in tags Hstore
        latest_result = await session.execute(
                select(OutputDetailVersion).where(
                    OutputDetailVersion.output_id.in_(output_detail_ids),
                    OutputDetailVersion.is_latest == True
                )
            )
        latest_output_version_details = latest_result.scalars().all()

        await update_output_details_hstore_tags(
        output_detail_versions=latest_output_version_details,      
        tag_id=output_ids.tag_id,
        tag_name="tag_name")

        # Commit changes
        await session.commit()
       
       
        return JSONResponse(
            status_code=202,
            content={"detail": "Synchronization completed successfully."}
        )

    except SQLAlchemyError as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error during synchronization: {str(e)}"
        ) from e
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error during synchronization: {str(e)}"
        ) from e

@router.put("/draft-status")
async def update_draft_status(
    payload: UpdateDraftStatusRequest,
    session: AsyncSession = Depends(get_session)
):
    # 1️⃣ Fetch output details
    result = await session.execute(
        select(OutputDetail).where(OutputDetail.id.in_(payload.output_ids))
    )
    output_detail_objs = result.scalars().all()

    # 2️⃣ Validate all IDs exist
    found_ids = {od.id for od in output_detail_objs}
    missing_ids = set(payload.output_ids) - found_ids
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"OutputDetail IDs not found: {missing_ids}"
        )

    # 3️⃣ Update draft status using helper
    await update_output_draft_status(
        session=session,
        output_detail_objs=output_detail_objs,
        toggle_mode=True
    )

    # 4️⃣ Commit changes
    await session.commit()

    return {
        "message": "Draft status updated successfully",
        "updated_ids": list(found_ids),
    }


@router.put("/bulk", response_model=List[OutputDetailRead])
async def bulk_update_output_details(
        request: BulkUpdateRequest,
        session: AsyncSession = Depends(get_session),
) -> List[OutputDetailRead]:
    """
    Update multiple OutputDetail records with the same data.
    
    Args:
        request (BulkUpdateRequest):
            Contains list of IDs and the data to update.
        session (AsyncSession):
            The database session dependency.
    
    Raises:
        HTTPException: If any OutputDetail with the given IDs is not found.
    
    Returns:
        List[OutputDetailRead]: List of updated OutputDetail instances.
    """
    if not request.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    
    # Fetch all records
    result = await session.execute(
        select(OutputDetail).where(OutputDetail.id.in_(request.ids))
    )
    db_output_details = result.scalars().all()
    
    # Check if all IDs were found
    if len(db_output_details) != len(request.ids):
        found_ids = {detail.id for detail in db_output_details}
        missing_ids = set(request.ids) - found_ids
        raise HTTPException(
            status_code=404,
            detail=f"Output details not found for IDs: {list(missing_ids)}"
        )
    
    # Update all records
    update_data = request.data.model_dump(exclude_unset=True)
    for db_output_detail in db_output_details:
        for key, value in update_data.items():
            setattr(db_output_detail, key, value)
        session.add(db_output_detail)
    
    await session.commit()
    
    # Refresh all records
    for db_output_detail in db_output_details:
        await session.refresh(db_output_detail)
    
    return db_output_details


@router.put("/{output_detail_id}", response_model=OutputDetailRead)
async def update_output_detail(
        output_detail_id: int,
        output_detail: OutputDetailUpdate,
        session: AsyncSession = Depends(get_session),
        ) -> OutputDetailRead:
    """
        Update an existing OutputDetail record by its ID.
        Args:
            output_detail_id (int):
                The ID of the OutputDetail to update.
            output_detail (OutputDetailUpdate):
                The data to update the OutputDetail with.
            session (AsyncSession, optional):
                The database session dependency.
        Raises:
            HTTPException: If the OutputDetail with the given ID is not found.
        Returns:
            OutputDetail: The updated OutputDetail instance.
    """
    result = await session.execute(
        select(OutputDetail).where(OutputDetail.id == output_detail_id))
    db_output_detail = result.scalars().first()
    if not db_output_detail:
        raise HTTPException(status_code=404, detail="Output detail not found")

    update_data = output_detail.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_output_detail, key, value)

    session.add(db_output_detail)
    await session.commit()
    await session.refresh(db_output_detail)
    return db_output_detail


@router.delete("/{output_detail_id}")
async def delete_output_detail(
        output_detail_id: int,
        session: AsyncSession = Depends(get_session)
        ) -> Dict[str, str]:
    """
        Delete an OutputDetail record by its ID.
        Args:
            output_detail_id (int): The ID of the OutputDetail to delete.
            session (AsyncSession, optional): The database session dependency.
        Raises:
            HTTPException: If the OutputDetail with the given ID is not found.
        Returns:
            dict: A confirmation message upon successful deletion.
    """
    result = await session.execute(
        select(OutputDetail).where(OutputDetail.id == output_detail_id)
    )
    db_output_detail = result.scalars().first()
    if not db_output_detail:
        raise HTTPException(status_code=404, detail="Output detail not found")

    await session.delete(db_output_detail)
    await session.commit()
    return {"detail": "Output detail deleted"}

@router.delete("/")
async def bulk_delete_output_details(
    output_ids_request: OutputDetailDeleteRequest,
) -> JSONResponse:
    """
    Bulk delete OutputDetail records by their IDs.
    Args:
        output_ids (list[int]): List of IDs of OutputDetails to delete.
    Raises:
        HTTPException: If no output IDs are provided.
    Returns:
        JSONResponse: A confirmation message upon successful deletion.
    """
    result = await delete_outputs_and_cleanup(output_ids_request.output_detail_ids)
    return result

@router.get("/{output_detail_id}/get_presigned_url")
async def get_presigned_url(
        output_detail_id: int,
        session: AsyncSession = Depends(get_session),
        current_user=Depends(authorize_user)
        ) -> Dict[str, str]:
    """
    Generate a presigned URL for downloading a watermarked file from S3.
    """
    is_reviewer = current_user.role.lower() == "reviewer"
    if is_reviewer:
        await authorize_reviewer(current_user, [output_detail_id], session)
    
    query = select(OutputDetail).where(OutputDetail.id == output_detail_id)
    result = await session.execute(query)
    output_detail = result.scalar_one_or_none()

    if not output_detail:
        raise HTTPException(status_code=404, detail="OutputDetail not found.")

    presigned_url = generate_presigned_url(output_detail.file_path)
    if not presigned_url:
        raise HTTPException(status_code=500,
                            detail="Could not generate presigned URL.")
    return {"url": presigned_url}


@router.get("/preview_local/{file_id}")
async def preview_local_file(
    file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user=Depends(authorize_user)
):
    """
    Serve the file stored on the application server so the frontend can preview it in-browser.
    - Returns a FileResponse with inline Content-Disposition so browsers will attempt to preview.
    """
    preview_files = {
        "1": "GSFLAB02I.rtf",
        "2": "tsfae01.pdf",
        "3": "tsfae01_document.doc",
        "4": "tsfae01_html_file.html",
        "5": "tsfae01_image.jpeg",
        "6": "tsfae01_svg_file.svg",
        "7": "tsfae01_document.docx"
    }

    file_name = preview_files.get(str(file_id))
    path = "/app/preview_input/" + file_name

    # Infer MIME type for proper preview in browser
    mime_type, _ = mimetypes.guess_type(file_name)
    media_type = mime_type or "application/octet-stream"

    headers = {"Content-Disposition": f'inline; filename="{file_name}"'}

    return FileResponse(str(path), media_type=media_type, headers=headers)