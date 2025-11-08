from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy import func, text
from app.models import  OutputDetail, OutputDetailVersion,  DatabaseReleaseTag, DatabaseRelease, Study, Compound
from fastapi import HTTPException
from typing import List
from sqlalchemy.orm import attributes, selectinload
from app.utils.enums import DocsSharedAs
from app.utils.audit_log import create_audit_log



async def validate_dbr_tag_name_output_conflict(
    session: AsyncSession,
    tag_name: str,
    source_id: int,
    payload_identifiers: list[str],
    database_release_name: str,
    study_name: str,    
    compound_name: str,
    file_paths: list[str]
    
):
    """
    Validate that the given tag_name is not linked with the same outputs (by identifier)
    in any other source.
    Raises HTTPException if a conflict exists.
    """
    # Check for conflicts in other sources
    try:
        conflict_result = await session.execute(
            select(OutputDetailVersion)
            .join(OutputDetail, OutputDetail.id == OutputDetailVersion.output_id)
            .join(
                DatabaseReleaseTag,
                text("output_detail_versions.tags ? database_release_tag.id::text")
            )
            .join(DatabaseRelease, DatabaseRelease.id == DatabaseReleaseTag.database_release_id)
            .join(Study, Study.id == DatabaseRelease.study_id)
            .join(Compound, Compound.id == Study.compound_id)
            .where(
                DatabaseReleaseTag.tag_name == tag_name,         # same tag name
                DatabaseReleaseTag.source_id != source_id,                          # different source
                OutputDetail.identifier.in_(payload_identifiers),                   # same outputs
                DatabaseRelease.name == database_release_name,  # same database release name
                Study.name == study_name,                       # same study name
                Compound.name == compound_name,                 # same compound name
                func.regexp_replace(
                    func.regexp_replace(
                        OutputDetail.file_path,
                        r'^[^/]+/[^/]+/',  # remove first two segments
                        ''
                    ),
                    r'/[^/]+$',           # remove last segment
                    ''
                ).in_(file_paths)  # compare only the middle part of file path
            )
        )
        conflicting_links = conflict_result.scalars().all()
    except Exception as e:
          print("Error during conflict check:", e)
    if conflicting_links:
            raise HTTPException(
                status_code=400,
                detail=[{
                    "field": "tag_name",
                    "message": (
                        f"Tag name '{tag_name}' is already linked with one or more outputs "
                        f"({', '.join(payload_identifiers)}) in another source."
                    )
                }]
            )
    



async def update_output_details_hstore_tags(
    output_detail_versions: List[OutputDetailVersion],
    tag_id: int,
    tag_name: str,
) -> None:
    """
    Updates the 'tags' HSTORE column for a list of OutputDetailVersion objects 
    with the given tag ID and name.
    
    Args:
        output_detail_versions: A list of OutputDetailVersion instances loaded in the session.
        tag_id: The ID of the DatabaseReleaseTag (used as the HSTORE key).
        tag_name: The name of the DatabaseReleaseTag (used as the HSTORE value).
    """
    if not output_detail_versions:
        return

    tag_key = str(tag_id)

    for od in output_detail_versions:

        # Add the new tag only if it doesn't already exist in the HSTORE
        if tag_key not in od.tags:
            od.tags[tag_key] = tag_name
            
            # CRITICAL: Flag the HSTORE column as modified to ensure the UPDATE is saved.
            attributes.flag_modified(od, "tags")

    # The caller (API endpoint) is responsible for calling session.commit()


async def remove_output_details_hstore_tags(
    output_detail_versions: List[OutputDetailVersion],
    tag_id: int,
) -> None:
    """
    Removes a specific tag ID (key) from the 'tags' HSTORE column for a list 
    of OutputDetail objects.
    
    Args:
        output_detail_versions: A list of OutputDetailVersion instances loaded in the session.
        tag_id: The ID of the DatabaseReleaseTag (used as the HSTORE key to remove).
    """
    if not output_detail_versions:
        return

    tag_key = str(tag_id)
    for od in output_detail_versions:
        # Check if tags is not None and the tag_key exists
        if od.tags is not None and tag_key in od.tags:
            del od.tags[tag_key]
            
            # CRITICAL: Flag the HSTORE column as modified to ensure the DELETE/UPDATE is saved.
            attributes.flag_modified(od, "tags")

    # The caller (API endpoint) is responsible for calling session.commit()


async def update_tag_name_in_output_versions(session, tag_id: int, new_tag_name: str):
    """
    Updates the tag name inside the 'tags' HSTORE column of OutputDetailVersion
    wherever the given tag_id is present.
    """
    tag_key = str(tag_id)

    result = await session.execute(
        select(OutputDetailVersion).where(
            OutputDetailVersion.tags.has_key(tag_key)
        )
    )
    versions = result.scalars().all() 

    for version in versions:
        if version.tags and tag_key in version.tags:
            version.tags[tag_key] = new_tag_name
            attributes.flag_modified(version, "tags")


async def update_output_draft_status(
    session: AsyncSession,
    output_detail_objs: List[OutputDetail],
    identify_as_draft: bool = True,
    toggle_mode: bool = False
):

    for od in output_detail_objs:
        old_value = od.docs_shared_as

        if toggle_mode:
            # Toggling logic
            if old_value is None or old_value == DocsSharedAs.PROD.value:
                new_env_value = DocsSharedAs.PREPROD.value
            else:
                new_env_value = DocsSharedAs.PROD.value
        else:
            # Normal mode (based on input flag)
            new_env_value = DocsSharedAs.PREPROD.value if identify_as_draft else DocsSharedAs.PROD.value

        od.docs_shared_as = new_env_value
        session.add(od)

        # Audit log
        if old_value != new_env_value:
            await create_audit_log(
                session=session,
                user_name="system",
                action="UPDATE",
                object_type="output_details",
                object_key=str(od.id),
                object_property="docs_shared_as",
                old_value=old_value,
                new_value=new_env_value
            )


async def clear_draft_status_from_orphan(
    session: AsyncSession,
    output_detail_ids: list[int]
):
    # 1️⃣ Fetch all OutputDetail objects in one go
    result = await session.execute(
        select(OutputDetail)
        .options(selectinload(OutputDetail.database_release_tags))
        .where(OutputDetail.id.in_(output_detail_ids))
    )

    # 2️⃣ Loop through result objects instead of querying inside loop
    output_details = result.scalars().all()

    for od in output_details:
        if len(od.database_release_tags) == 0:
            old_value = od.docs_shared_as
            od.docs_shared_as = None
            session.add(od)

            # Audit log
            if old_value != od.docs_shared_as:
                await create_audit_log(
                    session=session,
                    user_name="system",
                    action="UPDATE",
                    object_type="output_details",
                    object_key=str(od.id),
                    object_property="docs_shared_as",
                    old_value=old_value,
                    new_value=od.docs_shared_as
                )

    # 3️⃣ Single commit
    await session.commit()
   