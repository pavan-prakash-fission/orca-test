"""
    Celery task to get mapping of users to output IDs based on tags.
"""
from collections import defaultdict
from typing import List, Set, Dict, Tuple

from celery import shared_task
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import sync_engine
from app.models import (
    OutputDetail,
    ReportingEffortTag,
    DatabaseReleaseTag,
    User,
    Study,
    DatabaseRelease,
    ReportingEffort,
)
from app.utils.send_email import send_email


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def get_user_to_output_mapping(
        self,
        output_ids: List[int]
) -> Dict[str, List[str]]:
    """
    Celery task to fetch users associated with a list of output IDs.

    Args:
        output_ids: List of output IDs to process

    Returns:
        Dict mapping usernames to lists of ADR file paths they are associated.
    """
    try:
        with Session(sync_engine) as session:
            # 1. Fetch required OutputDetail objects and their related entities
            statement = (
                select(OutputDetail)
                .where(OutputDetail.id.in_(output_ids))
                .options(
                    # load the full relationship chain
                    selectinload(OutputDetail.reporting_effort)
                    .selectinload(ReportingEffort.database_release)
                    .selectinload(DatabaseRelease.study)
                    .selectinload(Study.compound),

                    # load tags and their linked distribution lists
                    selectinload(OutputDetail.reporting_effort_tags)
                    .selectinload(ReportingEffortTag.distribution_lists),
                    selectinload(OutputDetail.database_release_tags)
                    .selectinload(DatabaseReleaseTag.distribution_lists),
                )
            )

            results = session.exec(statement)
            outputs = results.unique().all()

            if not outputs:
                return {}

            # 2. Map users to their associated output IDs
            user_to_outputs: Dict[str, Set[Tuple[str, str, str, str]]] = defaultdict(set)

            for output in outputs:
                # safely fetch compound and study names via relationships
                compound_name = (
                    output.reporting_effort.database_release.study.compound.name
                    if output.reporting_effort
                    else "Unknown Compound"
                )
                study_name = (
                    output.reporting_effort.database_release.study.name
                    if output.reporting_effort
                    else "Unknown Study"
                )

                # Collect users from ReportingEffortTags
                for tag in output.reporting_effort_tags:
                    for username in tag.get_all_users():
                        user_to_outputs[username].add(
                            (
                                output.adr_filepath,
                                tag.tag_name,
                                compound_name,
                                study_name
                            )
                        )

                # Collect users from DatabaseReleaseTags
                for tag in output.database_release_tags:
                    for username in tag.get_all_users():
                        user_to_outputs[username].add(
                            (
                                output.adr_filepath,
                                tag.tag_name,
                                compound_name,
                                study_name
                            )
                        )

            if not user_to_outputs:
                return {}

            # ---- Send email notification to each user ----
            for username, path_tag_pairs in user_to_outputs.items():
                try:

                    # Fetch user's email from the users table
                    user_email = None
                    user_stmt = select(User).where(User.username == username)
                    user_result = session.exec(user_stmt).first()

                    if not user_result or not user_result.email:
                        continue

                    user_email = user_result.email

                    # For subject, pick one representative compound/study
                    sample = next(iter(path_tag_pairs))
                    _, _, compound_name, study_name = sample
                    subject = f"{compound_name}/{study_name} Updated SPACE files are available"

                    # Sort for consistent email output
                    sorted_pairs = sorted(list(path_tag_pairs))
                    table_rows = "".join(
                        f"<tr>"
                        f"<td style='padding:8px; border:1px solid #ddd;'>{tag_name}</td>"
                        f"<td style='padding:8px; border:1px solid #ddd;'>{file_path}</td>"
                        f"</tr>"
                        for file_path, tag_name, _, _ in sorted_pairs
                    )

                    html_body = f"""
                    <html>
                        <body style="font-family: Arial, sans-serif; line-height:1.5;">
                            <p>Hello <strong>{username}</strong>,</p>
                            <p>The programming team shared the following updates:</p>
                            <table style="border-collapse: collapse; width: 100%; max-width: 800px;">
                                <thead>
                                    <tr style="background-color: #97D07A;">
                                        <th style="padding:8px; border:1px solid #ddd; text-align: left;">Tag Name</th>
                                        <th style="padding:8px; border:1px solid #ddd; text-align: left;">File Path</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {table_rows}
                                </tbody>
                            </table>
                            <p>Best regards,<br><strong>The ORCA Team</strong></p>
                        </body>
                    </html>
                    """

                    send_email(to=user_email, subject=subject, body=html_body)

                except Exception:
                    continue

            # 3. Final user-to-output mapping for return
            final_mapping = defaultdict(set)
            for user, path_tag_pairs in user_to_outputs.items():
                for path, _, _, _ in path_tag_pairs:
                    final_mapping[user].add(path)

            return {
                user: sorted(list(paths))
                for user, paths in final_mapping.items()
            }

    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
    except Exception:
        raise


async def get_users_for_output_ids(
    session: AsyncSession,
    output_ids: List[int]
) -> Dict[int, Set[str]]:
    """
    Get all users who have access to each output ID via tags.
    
    Args:
        session: Async database session
        output_ids: List of output IDs to check
        
    Returns:
        Dict mapping output_id -> set of usernames who have access
    """
    if not output_ids:
        return {}
    
    # Fetch OutputDetail objects with all related tags
    statement = (
        select(OutputDetail)
        .where(OutputDetail.id.in_(output_ids))
        .options(
            selectinload(OutputDetail.reporting_effort_tags)
            .selectinload(ReportingEffortTag.distribution_lists),
            selectinload(OutputDetail.database_release_tags)
            .selectinload(DatabaseReleaseTag.distribution_lists),
        )
    )
    result = await session.execute(statement)
    outputs = result.unique().scalars().all()
    
    # Map output_id -> set of users
    output_to_users: Dict[int, Set[str]] = {}
    
    for output in outputs:
        users = set()
        
        # Collect users from ReportingEffortTags
        for tag in output.reporting_effort_tags:
            users.update(tag.get_all_users())
        
        # Collect users from DatabaseReleaseTags
        for tag in output.database_release_tags:
            users.update(tag.get_all_users())
        
        output_to_users[output.id] = users
    
    return output_to_users


async def get_accessible_output_ids_for_reviewer(
    session: AsyncSession,
    username: str,
    output_ids: List[int]
) -> List[int]:
    """
    Get output IDs that a reviewer has access to via tags.
    
    Args:
        session: Async database session
        username: Reviewer's username
        output_ids: List of output IDs to filter
        
    Returns:
        List of output IDs the reviewer can access
    """
    if not output_ids:
        return []
    
    # Get users for each output
    output_to_users = await get_users_for_output_ids(session, output_ids)
    
    # Filter to only outputs this user has access to
    accessible = [
        output_id
        for output_id, users in output_to_users.items()
        if username in users
    ]
    
    return accessible


async def get_reviewer_accessible_output_ids_query(
    session: AsyncSession,
    username: str
) -> Set[int]:
    """
    Get ALL output IDs that a reviewer has access to (for query filtering).
    This is used to filter the initial query rather than post-processing.
    
    Args:
        session: Async database session
        username: Reviewer's username
        
    Returns:
        Set of all output IDs the reviewer can access
    """
    # First, get all output IDs that have ANY tags
    stmt = (
        select(OutputDetail.id)
        .join(
            OutputDetail.reporting_effort_tags,
            isouter=False  # INNER JOIN - only outputs with tags
        )
    )
    result = await session.execute(stmt)
    output_ids_with_re_tags = set(result.scalars().all())
    
    # Get output IDs with database release tags
    stmt = (
        select(OutputDetail.id)
        .join(
            OutputDetail.database_release_tags,
            isouter=False
        )
    )
    result = await session.execute(stmt)
    output_ids_with_db_tags = set(result.scalars().all())
    
    # Combine all tagged outputs
    all_tagged_output_ids = list(output_ids_with_re_tags | output_ids_with_db_tags)
    
    if not all_tagged_output_ids:
        return set()
    
    # Now check which ones this user has access to
    accessible = await get_accessible_output_ids_for_reviewer(
        session, username, all_tagged_output_ids
    )
    
    return set(accessible)
