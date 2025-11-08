from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy import func, text
from app.models import  OutputDetail, OutputDetailVersion,  DatabaseReleaseTag, DatabaseRelease, Study, Compound
from fastapi import HTTPException



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