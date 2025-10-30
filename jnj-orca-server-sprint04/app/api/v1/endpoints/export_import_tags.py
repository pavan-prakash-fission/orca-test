import io
import os
import pandas as pd


from fastapi import APIRouter, File, UploadFile, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.models.database_release_tag import DatabaseReleaseTag
from app.models.reporting_effort_tag import ReportingEffortTag
from app.models.associations import OutputDetailDatabaseReleaseTagLink, OutputDetailTagLink
from app.models import Source, Compound, Study
from app.models.output_detail import OutputDetail
from app.models.user import User
from app.utils.s3_boto_client import get_s3_client, download_s3_files
from app.models.distribution_list import DistributionList
from app.models.database_release import DatabaseRelease
from app.models.reporting_effort import ReportingEffort
from app.schemas.export_import_tags import ImportTagsResponse


router = APIRouter()

@router.get("/sources/{source_type}/tags/{tag_id}/export")
async def export_tags_excel(
    source_type: str,
    tag_id: int,
    session: AsyncSession = Depends(get_session)
):
    """
    Export tag data for a specific DBR or RE as an Excel file.
    """

    if source_type.lower() == "dbr":
        result = await session.execute(
            select(DatabaseReleaseTag)
            .options(
                selectinload(DatabaseReleaseTag.distribution_lists),
                selectinload(DatabaseReleaseTag.output_details),
            )
            .where(DatabaseReleaseTag.id == tag_id)
        )
        tag = result.scalars().first()
        
    elif source_type.lower() == "re":
        result = await session.execute(
            select(ReportingEffortTag)
            .options(
                selectinload(ReportingEffortTag.distribution_lists),
                selectinload(ReportingEffortTag.output_details),
            )
            .where(ReportingEffortTag.id == tag_id)
        )
        tag = result.scalars().first()
    else:
        raise HTTPException(status_code=404, detail="source_type must be 'dbr' or 're'")
    
    if not tag:
        raise HTTPException(status_code=404, detail=f"{source_type.upper()} Tag not found")

    data = []
    for file in tag.output_details:
        data.append({
            "Tag_Name": tag.tag_name,
            "Reason": tag.reason.value,
            "ID": file.identifier,
            "Version": 1,  # Not yet implemented
            "Path": file.file_path,
            "User": ", ".join(tag.users),
            "User_List": ", ".join([dl.name for dl in tag.distribution_lists]),
        })
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No associated output details found for this tag"
        )

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=f"Export_Tags_{tag_id}")
    output.seek(0)

    
    filename = f"tags_{source_type}_{tag_id}.xlsx" 
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(output, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@router.post("/tags/{tag_level}/id/{dbr_id}/import", response_model=ImportTagsResponse)
async def import_tags_excel(
    import_type: str = Form(...),
    tag_name: str = Form(None),
    tag_level: str = None,
    dbr_id: int = None,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session)
):
    # Validate file extension
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File type should be xlsx")

    # Read Excel file
    content = await file.read()
    df = pd.read_excel(content)
    df.columns = [col.strip().lower() for col in df.columns]

    # Required columns
    required_cols_new = {"tag_name", "reason", "id", "version", "path", "user", "user_list"}
    required_cols_existing = required_cols_new - {"tag_name"}
    missing_cols = set()

    # Validate missing columns
    if import_type == "new":
        missing_cols = required_cols_new - set(df.columns)
        tag_name = await validate_tag_name(df, import_type, dbr_id, session)
    elif import_type == "existing":
        missing_cols = required_cols_existing - set(df.columns)
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"These columns are missing from the input sheet: {', '.join(missing_cols)}")

    reason = validate_reason(df)
    all_users, unregistered_users = await validate_users(df, session, tag_name, import_type, dbr_id)
    all_user_lists, unregistered_user_lists = await validate_distribution_lists(df, session)
    all_files, unlinked_files = await validate_output_details(df, session, dbr_id)

    if import_type == "new":
        db_tag = DatabaseReleaseTag(
            database_release_id=dbr_id,
            tag_name=tag_name,
            reason=reason,
            users=list(all_users),
            distribution_lists=list(all_user_lists),
            output_details=list(all_files),
        )
        session.add(db_tag)
        await session.commit()
    else:
        tag_query = select(DatabaseReleaseTag).options(
                selectinload(DatabaseReleaseTag.distribution_lists),
                selectinload(DatabaseReleaseTag.output_details),
            ).where(DatabaseReleaseTag.database_release_id == dbr_id, DatabaseReleaseTag.tag_name == tag_name)
        tag_result = await session.execute(tag_query)
        db_tag = tag_result.scalar_one_or_none()
        if not db_tag:
            raise HTTPException(status_code=404, detail="Tag not found for update")
        

        existing_lists = {dl.name: dl for dl in db_tag.distribution_lists}
        new_lists = {dl.name: dl for dl in all_user_lists}
        

        existing_files = {(od.identifier, od.file_path): od for od in db_tag.output_details}
        new_files = {(od.identifier, od.file_path): od for od in all_files}
        
        db_tag.users = list(all_users)
        db_tag.distribution_lists = list({**existing_lists, **new_lists}.values())
        db_tag.output_details = list({**existing_files, **new_files}.values())
        db_tag.reason = reason
        session.add(db_tag)
        await session.commit()
        await session.refresh(db_tag)

    return {
        "status": "success",
        "unlinked_files": unlinked_files,
        "unregistered_users": unregistered_users,
        "unregistered_user_lists": unregistered_user_lists,
    }


async def validate_tag_name(df, import_type, dbr_id, session):
    if import_type == "new":
        tag_names = df["tag_name"].dropna().unique()
        if len(tag_names) != 1:
            raise HTTPException(status_code=400, detail="Only one tag name is allowed")
        tag_name = tag_names[0]
        tag_query = select(DatabaseReleaseTag).where(
            DatabaseReleaseTag.tag_name == tag_name,
            DatabaseReleaseTag.database_release_id == dbr_id
        )
        tag_result = await session.execute(tag_query)
        if tag_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Tag name already exists at this level")
    return tag_name

def validate_reason(df):
    reasons = df["reason"].dropna().unique()
    if len(reasons) != 1:
        raise HTTPException(status_code=400, detail="Only one reason is allowed")
    return reasons[0]

async def validate_distribution_lists(df, session):
    '''
    Validate the distribution lists and segregate them into registered and unregistered lists.
    '''
    all_list_names = set()
    for lists_str in df["user_list"].dropna():
        lists = [l.strip() for l in str(lists_str).split(",") if l.strip()]
        all_list_names.update(lists)

    dl_query = select(DistributionList).where(DistributionList.name.in_(all_list_names))
    result = await session.execute(dl_query)
    registered_list_objs = list(result.scalars())
    registered_list_names = {dl.name for dl in registered_list_objs}

    unregistered_user_lists = list(all_list_names - registered_list_names)
    all_user_lists = registered_list_objs

    return all_user_lists, unregistered_user_lists

async def validate_output_details(df, session, dbr_id):
    '''
    Validate the output details and return linked and unlinked files.
    '''
    all_paths = df["path"].dropna().astype(str)

    source_stmt = (
        select(Source.name, Compound.name, Study.name, DatabaseRelease.name)
        .join(Compound, Compound.source_id == Source.id)
        .join(Study, Study.compound_id == Compound.id)
        .join(DatabaseRelease, DatabaseRelease.study_id == Study.id)
        .where(DatabaseRelease.id == dbr_id)
    )
    result = await session.execute(source_stmt)
    dbr_name_row = result.first()
    if not dbr_name_row:
        raise HTTPException(status_code=404, detail="DatabaseRelease not found")
    source_name, compound_name, study_name, db_name = dbr_name_row

    updated_paths = []
    for path in all_paths:
        parts = path.split("/")
        env_idx = next((i for i, p in enumerate(parts) if p.upper() in {"PROD", "PREPROD", "REPO"}), None)
        if env_idx is not None:
            before_env = parts[:env_idx]
            after_env = parts[env_idx + 4:]
            new_path = "/".join(
                before_env +
                [source_name, compound_name, study_name, db_name] +
                after_env
            )
            updated_paths.append(new_path)
        else:
            raise HTTPException(status_code=500, detail=f"unable to parse path: {path}")

    df["path"] = updated_paths
    file_pairs = {(str(row["id"]), row["path"]) for _, row in df.iterrows()}
    od_query = select(OutputDetail).where(
        OutputDetail.identifier.in_([fp[0] for fp in file_pairs]),
        OutputDetail.file_path.in_([fp[1] for fp in file_pairs])
    )
    result = await session.execute(od_query)
    output_details = list(result.scalars())

    found_pairs = {(od.identifier, od.file_path) for od in output_details}

    all_files = []
    unlinked_files = []
    for file_id, file_path in file_pairs:
        if (file_id, file_path) in found_pairs:
            od = next(od for od in output_details if od.identifier == file_id and od.file_path == file_path)
            all_files.append(od)
        else:
            unlinked_files.append(file_path)

    return all_files, unlinked_files

async def validate_users(df, session, tag_name, import_type, dbr_id):
    '''
    Validate the users and segregate them into registered and unregistered lists.
    For 'existing' import_type, merge users from df and existing tag users.
    '''
    all_usernames = set()
    for users_str in df["user"].dropna():
        users = [u.strip() for u in str(users_str).split(",") if u.strip()]
        all_usernames.update(users)

    if import_type == "existing":
        tag_query = select(DatabaseReleaseTag).where(
            DatabaseReleaseTag.tag_name == tag_name,
            DatabaseReleaseTag.database_release_id == dbr_id
        )
        tag_result = await session.execute(tag_query)
        db_tag = tag_result.scalar_one_or_none()
        if db_tag and db_tag.users:
            all_usernames.update(db_tag.users)

    user_query = select(User).where(User.username.in_(all_usernames))
    result = await session.execute(user_query)
    registered_user_objs = list(result.scalars())
    registered_usernames = {user.username for user in registered_user_objs}

    unregistered_users = list(all_usernames - registered_usernames)
    return registered_usernames, unregistered_users
