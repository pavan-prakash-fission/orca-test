"""
    Bulk deletes outputs and cleans up orphan tags.
    Uses async SQLAlchemy sessions with proper transaction handling.
"""

from typing import List

from sqlalchemy import delete, exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.models import (
    OutputDetail,
    OutputDetailDatabaseReleaseTagLink,
    DatabaseReleaseTag,
    DatabaseReleaseTagDistributionListLink,
)
from app.core.db import async_session


async def _bulk_delete_links(
        session: AsyncSession,
        model,
        column,
        ids: List[int]
) -> None:
    """Helper to delete link records for given output IDs."""
    await session.execute(delete(model).where(column.in_(ids)))


async def _cleanup_orphan_tags(
        session: AsyncSession
) -> None:
    """Helper to delete orphaned tags with no linked outputs."""
    orphan_cleanup_targets = [
      
        (
            DatabaseReleaseTag,
            OutputDetailDatabaseReleaseTagLink.database_release_tag_id,
            DatabaseReleaseTag.id,
            DatabaseReleaseTagDistributionListLink,
            DatabaseReleaseTagDistributionListLink.database_release_tag_id
        ),
    ]

    for (
        tag_model,
        link_column,
        tag_id_column,
        dist_link_model,
        dist_link_column
    ) in orphan_cleanup_targets:

        # Find orphan tag IDs
        orphan_ids = select(
            tag_id_column
            ).where(
                ~exists().where(
                    link_column == tag_id_column
                    )
                ).scalar_subquery()

        # Delete DistributionList links first
        await session.execute(
            delete(
                dist_link_model
            ).where(
                dist_link_column.in_(
                    orphan_ids
                    )
                )
        )

        # Delete the orphan tags themselves
        await session.execute(
            delete(
                tag_model
                ).where(
                    tag_id_column.in_(
                        orphan_ids
                    )
                )
        )

async def delete_outputs_and_cleanup(
        output_ids: List[int]
) -> JSONResponse:
    """
    Bulk delete outputs and clean orphaned tags.

    Args:
        output_ids (List[int]): IDs of outputs to delete.

    Returns:
        JSONResponse: Summary of the cleanup action.
    """

    async with async_session() as session:
        try:
            # Delete from link tables
            await _bulk_delete_links(
                session=session,
                model=OutputDetailTagLink,
                column=OutputDetailTagLink.output_detail_id,
                ids=output_ids
            )
            await _bulk_delete_links(
                session=session,
                model=OutputDetailDatabaseReleaseTagLink,
                column=OutputDetailDatabaseReleaseTagLink.output_detail_id,
                ids=output_ids
            )

            # Delete main output entries
            await session.execute(
                delete(
                    OutputDetail
                    ).where(
                        OutputDetail.id.in_(
                            output_ids
                        )
                )
            )

            # Clean orphaned tags
            await _cleanup_orphan_tags(
                session=session
            )

            await session.commit()

            return JSONResponse(
                status_code=200,
                content={
                    "detail": "Outputs and Orphan Tags deleted successfully."
                }
            )

        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Database error during deletion : {exc}"
            ) from exc
