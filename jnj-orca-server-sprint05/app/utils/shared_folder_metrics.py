import json
from typing import List, Dict, Optional, Tuple, Any, Set
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.future import select
from sqlalchemy import and_, case

from app.models import (
    SharedFolderMetric,
    DistributionList,
    OutputDetail,
    DatabaseReleaseTagDistributionListLink,
    DatabaseReleaseTag
)
from app.core.db import get_session


def _parse_timestamp_utc(value: Optional[str]):
    """Convert ISO string timestamp into UTC datetime (aware)."""
    if not value:
        return None
    try:

        # Parse ISO timestamp
        dt = datetime.fromisoformat(value)

        # Normalize to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        return dt
    except Exception:
        return None


def extract_metrics_from_audit_logs(
    audit_logs: List[Dict[str, str]]
) -> Tuple[
    Dict[str, Any],
    Set[str],
    Set[str],
    List[int],
    List[int],
    List[Dict[str, str]],
    List[Dict[str, str]]
]:
    """
        Extract shared folder metrics from audit logs.
        Args:
            audit_logs:
                List of audit log entries related to the shared folder action
    Returns:
        A tuple containing:
            - metrics: Dict of shared folder metric fields
            - user_list: Set of usernames the folder was shared to
            - distribution_lists: List of distribution list IDs
            - output_details: List of output detail dicts
    """
    metrics: Dict[str, Any] = dict()
    user_list: Set[str] = set()
    old_users: Set[str] = set()
    distribution_lists: List[int] = list()
    old_dist_lists: List[int] = list()
    output_details: List[Dict[str, str]] = list()
    output_details_old_values: List[Dict[str, str]] = list()

    timestamp_str = audit_logs[0].get("timestamp")
    ts_value = _parse_timestamp_utc(timestamp_str)

    metrics["file_shared_from_ts"] = ts_value

    metrics['tag_id'] = _parse_int(audit_logs[0].get("object_key"))

    for log in audit_logs:
        prop = log.get("object_property")

        if prop == "users": 
            # Get new users list
            user_list = set(json.loads(log.get("new_value", "[]")))

            try:
                # If users list got updated, get old users list too
                if log.get("old_value") is not None:
                    old_users = set(json.loads(log.get("old_value", "[]")))

            except json.JSONDecodeError:
                old_users = set()

        elif prop == "distribution_lists":
            # Get new distribution lists
            distribution_lists = json.loads(log.get("new_value", "[]"))

            # If distribution lists got updated, get old distribution lists too
            try:
                if log.get("old_value") is not None:
                    old_dist_lists = json.loads(log.get("old_value", "[]"))

            except json.JSONDecodeError:
                old_dist_lists = set()

        elif prop == "output_details":
            # Get new output details
            output_details = json.loads(log.get("new_value", "[]"))

            # If output details got updated, get old output details too
            try:
                if log.get("old_value") is not None:
                    output_details_old_values = json.loads(
                        log.get(
                            "old_value",
                            "[]"
                        )
                    )

            except json.JSONDecodeError:
                output_details_old_values = set()

        elif prop == "reason":
            metrics["comment"] = log.get("new_value")

        elif prop == "tag_name":
            metrics["tag_name"] = log.get("new_value")

        if log.get("user_name"):
            metrics["file_shared_by"] = log.get("user_name")

    return (
        metrics,
        user_list,
        old_users,
        distribution_lists,
        old_dist_lists,
        output_details,
        output_details_old_values,
    )


async def _get_users_from_distribution_lists(
    db: AsyncSession,
    distribution_list_ids: List[int]
) -> Set[str]:
    """
    Fetch users from distribution lists.
    """
    if not distribution_list_ids:
        return set()

    result = await db.execute(
        select(DistributionList.users).where(
            DistributionList.id.in_(distribution_list_ids)
        )  # type: ignore
    )  # type: ignore

    users: Set[str] = set()
    for user_list in result.scalars().all():
        if user_list:
            users.update(user_list)
    return users


async def _get_output_details_by_ids(
        db: AsyncSession,
        output_ids: List[int]
) -> Dict[str, OutputDetail]:

    """
        Fetch OutputDetail objects by their IDs.
    """
    results = await db.execute(
        select(
            OutputDetail
        ).where(
            OutputDetail.id.in_(output_ids)  # type: ignore
            )
        )  # type: ignore
    output_map = {str(output.id): output for output in results.scalars().all()}

    return output_map


def _parse_int(value: Optional[str]) -> Optional[int]:
    """
        Safely parse an integer from a string, returning None on failure.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_versions(
        output_details: List[Dict[str, str]]
) -> Dict[int, Tuple[Optional[int], Optional[int], Optional[int]]]:
    """
        Map output detail IDs to their version components.
        Args:
            output_details: List of output detail dicts from audit logs
        Returns:
            Dict mapping output detail ID to (major, minor, patch) version tuple
    """
    version_map = {}

    for item in output_details:
        vid = item.get("id")
        ver = item.get("version")

        if vid is None or ver is None:
            continue

        # Always treat version as string
        parts = str(ver).split(".")
        major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else None
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

        version_map[int(vid)] = (major, minor, patch)

    return version_map



def build_shared_metric_data(
    metrics: Dict[str, Any],
    output_detail: OutputDetail,
    user: str,
    output_info: Dict[str, str],
) -> Dict[str, Any]:

    """
        Build shared folder metric data dict.

        Args:
            metrics: Base metrics dict
            output_detail: OutputDetail object
            user: Username the folder was shared to
            output_info: Output detail dict from audit log
        Returns:
            Dict of shared folder metric fields
    """
    version_str = output_info.get("version")
    version_parts = []

    if version_str and version_str.lower() != "none":
        version_parts = version_str.split(".")
    elif isinstance(version_str, (int, float)):
        version_parts = [str(version_str)]

    return {
        **metrics,
        "output_detail_id": output_detail.id,
        "compound": output_detail.compound_name,
        "study": output_detail.study_name,
        "dbr": output_detail.database_release_name,
        "re": output_detail.reporting_effort_name,
        "file_shared": output_detail.adr_filepath,
        "file_name": output_detail.adr_filepath.split("/")[-1] if output_detail.adr_filepath else None,
        "file_version_major": _parse_int(version_parts[0]) if len(version_parts) > 0 else None,
        "file_version_minor": _parse_int(version_parts[1]) if len(version_parts) > 1 else None,
        "file_version_patch": _parse_int(version_parts[2]) if len(version_parts) > 2 else None,
        "file_shared_to": user
    }


async def _generate_shared_metrics(
    db: AsyncSession,
    metrics: Dict[str, Any],
    user_list: Set[str],
    output_details: List[Dict[str, str]],
) -> List[SharedFolderMetric]:
    """
        Generate SharedFolderMetric objects.
        Args:
            db: Async database session
            metrics: Base metrics dict
            user_list: Set of usernames the folder was shared to
            output_details: List of output detail dicts from audit logs
        Returns:
            List of SharedFolderMetric objects
    """
    if not user_list or not output_details:
        return []
    output_ids = [int(output["id"]) for output in output_details if output.get("id")]
    output_map = await _get_output_details_by_ids(db, output_ids)

    shared_metrics: List[SharedFolderMetric] = []
    seen = set()
    for user in user_list:
        for output in output_details:
            key = (user, output["id"])
            if key in seen:
                continue
            seen.add(key)
            obj = output_map.get(str(output.get("id")))
            if not obj:
                continue

            metric_data = build_shared_metric_data(metrics, obj, user, output)
            shared_metrics.append(SharedFolderMetric(**metric_data))
    return shared_metrics


async def create_shared_folder_metrics(
        db: AsyncSession,
        audit_logs: List[Dict[str, str]]
     ):
    """
        Shared folder metrics for Tag Creation from audit logs.

        Args:
            db: Async database session
            audit_logs: List of audit log entries related to the shared folder action
    """
    metrics, user_list, _, distribution_lists, _, output_details, _ = extract_metrics_from_audit_logs(audit_logs)

    dist_users = await _get_users_from_distribution_lists(db, distribution_lists)
    user_list.update(dist_users)

    shared_metrics = await _generate_shared_metrics(
        db=db,
        metrics=metrics,
        user_list=user_list,
        output_details=output_details
    )

    if not shared_metrics:
        return

    db.add_all(shared_metrics)
    await db.commit()


async def _update_metrics_for_user_addition(
    db: AsyncSession,
    metrics: Dict[str, Any],
    user_list: Set[str],
    object_id: int
):
    """
    Add users to shared folder metrics if they don't already exist.
    """
    if not user_list:
        return

    # Fetch active outputs for this tag
    result = await db.execute(
        select(
            SharedFolderMetric.output_detail_id,
            SharedFolderMetric.comment,
            SharedFolderMetric.tag_name,
        )
        .where(
            and_(
                SharedFolderMetric.tag_id == object_id,
                SharedFolderMetric.file_shared_to_ts.is_(None),
            )
        )
    )

    rows = result.all()
    if not rows:
        return
    
    # Get unique output IDs and convert to the format expected by _generate_shared_metrics
    active_output_ids = list({int(row[0]) for row in rows})
    active_output_dicts = [{"id": str(oid)} for oid in active_output_ids]
    
    reason = rows[0][1]
    tag_name = rows[0][2]

    if "comment" not in metrics:
        metrics["comment"] = rows[0][1]

    if "tag_name" not in metrics:
        metrics["tag_name"] = rows[0][2]

    metrics["tag_id"] = object_id

    # Get existing user-output combinations for this tag
    existing = await db.execute(
        select(
            SharedFolderMetric.file_shared_to,
            SharedFolderMetric.output_detail_id,
        ).where(
            and_(
                SharedFolderMetric.tag_id == object_id,
                SharedFolderMetric.file_shared_to_ts.is_(None),
                SharedFolderMetric.file_shared_to.in_(user_list),
            )
        )
    )

    existing_pairs = {(row[0], row[1]) for row in existing.all()}

    # Filter users who actually need new records
    new_user_list = set()
    for user in user_list:
        # Check if this user needs ANY new records
        needs_records = any(
            (user, oid) not in existing_pairs 
            for oid in active_output_ids
        )
        if needs_records:
            new_user_list.add(user)

    if not new_user_list:
        return

    # Generate SharedFolderMetric objects - call ONCE with all users
    # _generate_shared_metrics will handle the loops internally
    shared_metrics = await _generate_shared_metrics(
        db=db,
        metrics=metrics,
        user_list=new_user_list,  # Pass all new users at once
        output_details=active_output_dicts,  # Pass all outputs at once
    )

    # Filter out duplicates that already exist
    final_metrics = []
    for metric in shared_metrics:
        if (metric.file_shared_to, metric.output_detail_id) not in existing_pairs:
            final_metrics.append(metric)
            existing_pairs.add((metric.file_shared_to, metric.output_detail_id))

    if final_metrics:
        db.add_all(final_metrics)

async def _update_metrics_for_user_removal(
    db: AsyncSession,
    user_list: Set[str],
    deleted_timestamp: datetime | None,
    object_id: int | None
):
    """
        Remove users from shared folder metrics.
    """
    if not user_list:
        return

    await db.execute(
        SharedFolderMetric.__table__
            .update()
            .where(
                and_(
                    SharedFolderMetric.tag_id == object_id,
                    SharedFolderMetric.file_shared_to_ts.is_(None),
                    SharedFolderMetric.file_shared_to.in_(user_list)
                )
            ).values(
                file_shared_to_ts=deleted_timestamp
            )
    )


async def _update_metrics_for_outputs_added_to_tag(
    db: AsyncSession,
    metrics: Dict[str, Any],
    output_details: List[Dict[str, str]],
    object_id: int | None
):
    """
        Add output details to shared folder metrics.
    """

    if not output_details or not object_id:
        return

    result = await db.execute(
        select(
            SharedFolderMetric.file_shared_to,
            SharedFolderMetric.comment,
            SharedFolderMetric.tag_name
        )
        .where(
            and_(
                SharedFolderMetric.tag_id == object_id,
            )
        )
    )

    result = result.all()

    tag_result = await db.execute(
        select(DatabaseReleaseTag)
        .where(DatabaseReleaseTag.id == object_id)
        .options(
            selectinload(DatabaseReleaseTag.distribution_lists)
        )
    )
    tag = tag_result.scalar_one_or_none()
    if not tag:
        return
    users = tag.get_all_users()
    if not users:
        return
    if result:
        reason = result[0][1]
        tag_name = result[0][2]
    else:
        reason = None
        tag_name = None

    # Update metrics
    metrics["tag_name"] = tag_name
    metrics["comment"] = reason
    metrics["tag_id"] = object_id

    # Create SharedFolderMetric entries for added output details
    shared_metrics = await _generate_shared_metrics(
        db=db,
        metrics=metrics,
        user_list=users,
        output_details=output_details
    )
    if shared_metrics:
        db.add_all(shared_metrics)


async def _update_metrics_for_outputs_removed_from_tag(
    db: AsyncSession,
    output_ids: Set[int],
    deleted_timestamp: datetime | None,
    object_id: int | None
):
    """
        Remove output details from shared folder metrics.
    """
    if not output_ids or not object_id:
        return

    await db.execute(
        SharedFolderMetric.__table__
            .update()
            .where(
                and_(
                    SharedFolderMetric.tag_id == object_id,
                    SharedFolderMetric.output_detail_id.in_(output_ids),
                    SharedFolderMetric.file_shared_to_ts.is_(None)
                )
            ).values(
                file_shared_to_ts=deleted_timestamp
            )
    )


async def _update_metrics_for_output_version_update(
    db: AsyncSession,
    output_details: List[Dict[str, str]],
    object_id: int | None
):
    """
        Update output detail versions in shared folder metrics.
    """
    if not output_details or not object_id:
        return

    version_map = _map_versions(output_details)
    ids = list(version_map.keys())

    major_case = case(
        {oid: major for oid, (major, _, _) in version_map.items()},
        value=SharedFolderMetric.output_detail_id
    )

    minor_case = case(
        {oid: minor for oid, (_, minor, _) in version_map.items()},
        value=SharedFolderMetric.output_detail_id
    )

    patch_case = case(
        {oid: patch for oid, (_, _, patch) in version_map.items()},
        value=SharedFolderMetric.output_detail_id
    )

    await db.execute(
        SharedFolderMetric.__table__.update()
        .where(
            and_(
                SharedFolderMetric.output_detail_id.in_(ids),
                SharedFolderMetric.tag_id == object_id,
                SharedFolderMetric.file_shared_to_ts.is_(None)
            )
        )
        .values(
            file_version_major=major_case,
            file_version_minor=minor_case,
            file_version_patch=patch_case
        )
    )


async def update_shared_folder_metrics_for_tag_update(
    db: AsyncSession,
    audit_logs: List[Dict[str, str]]
):
    """
        Shared folder metrics for Tag Update from audit logs.
        Args:
            db: Async database session
            audit_logs: List of audit log entries related to the shared folder action
    """
    metrics, user_list, old_users, distribution_lists, old_dist_lists, output_details, output_details_old = extract_metrics_from_audit_logs(audit_logs)

    # Metrics contains the updated fields
    # Check for the existing records and update them accordingly

    object_id = _parse_int(audit_logs[0].get("object_key"))

    object_properties = metrics.keys()

    if user_list is not None:
        # Identify users added and removed
        # Get users from distribution lists
        new_distribution_list_users = await _get_users_from_distribution_lists(db, distribution_lists)
        old_distribution_list_users = await _get_users_from_distribution_lists(db, old_dist_lists)

        # Combine with old and new users list
        new_users = user_list.union(new_distribution_list_users)
        old_users = old_users.union(old_distribution_list_users)

        # Newly added users
        added_users = new_users - old_users
        # Removed users
        removed_users = old_users - new_users
        if added_users:
            await _update_metrics_for_user_addition(
                        db=db,
                        metrics=metrics,
                        user_list=added_users,
                        object_id=object_id
                    )
        if removed_users:
            # Mark existing metrics as file_shared_to_ts
            deleted_timestamp = _parse_timestamp_utc(audit_logs[0].get("timestamp"))

            await _update_metrics_for_user_removal(
                db=db,
                user_list=removed_users,
                deleted_timestamp=deleted_timestamp,
                object_id=object_id
            )
    await db.commit()

    if "tag_name" in object_properties or "comment" in object_properties:
        # If either field is being updated, we need to update the old value
        await db.execute(
            SharedFolderMetric.__table__
                .update()  # type: ignore
                .where(
                    and_(
                        SharedFolderMetric.tag_id == object_id,
                        SharedFolderMetric.file_shared_to_ts.is_(None) 
                    )  # type: ignore
                ).values(
                    {
                        key: metrics[key]
                        for key in ["tag_name", "comment"] if key in metrics
                    }
                )
        )

    if output_details is not None:
        new_value = output_details
        old_values = output_details_old

        # Find differences between new and old output details
        new_output_ids = {int(output["id"]) for output in new_value if output.get("id")}
        old_output_ids = {int(output["id"]) for output in old_values if output.get("id")}

        # Identify added and removed output IDs
        added_output_ids = new_output_ids - old_output_ids
        removed_output_ids = old_output_ids - new_output_ids
        # Handle added output details
        if added_output_ids:

            # Create a map from the added list to lookup full details
            new_item_map = {int(item["id"]): item for item in output_details}
            new_output_details = [
                new_item_map[oid]
                for oid in added_output_ids
                if oid in new_item_map
            ]

            await _update_metrics_for_outputs_added_to_tag(
                db=db,
                metrics=metrics,
                output_details=new_output_details,
                object_id=object_id
            )

        elif removed_output_ids:
            # Mark existing metrics as file_shared_to_ts
            deleted_timestamp = _parse_timestamp_utc(audit_logs[0].get("timestamp"))

            await _update_metrics_for_outputs_removed_from_tag(
                db=db,
                output_ids=removed_output_ids,
                deleted_timestamp=deleted_timestamp,
                object_id=object_id
            )

        # if outputs are not added or removed then the updates are only for version
        else:
            await _update_metrics_for_output_version_update(
                db=db,
                output_details=new_value,
                object_id=object_id
            )

    await db.commit()


async def _get_tag_ids_for_distribution_list(
    db: AsyncSession,
    distribution_list_id: int | None
) -> List[int]:
    """
        Fetch associated tag IDs for a distribution list.
    """
    result = await db.execute(
        select(
            DatabaseReleaseTagDistributionListLink.database_release_tag_id
        ).where(
            DatabaseReleaseTagDistributionListLink.distribution_list_id == distribution_list_id
        )
    )
    tag_ids = list(set(result.scalars().all()))
    return tag_ids


async def update_shared_folder_metrics_for_dl_update(
        db: AsyncSession,
        audit_log: Dict[str, str]
):
    """
        Shared folder metrics for Distribution List Update from audit logs.
        Args:
            db: Async database session
            audit_log: Audit log entry related to the distribution list action
    """
    metrics, new_users, old_users, _, _, _, _ = extract_metrics_from_audit_logs([audit_log])
    tag_ids = await _get_tag_ids_for_distribution_list(
        db=db,
        distribution_list_id=_parse_int(audit_log.get("object_key"))
    )
    if not tag_ids:
        return

    # Identify users added and removed
    added_users = new_users - old_users
    removed_users = old_users - new_users
    if added_users:
        for tag_id in tag_ids:
            await _update_metrics_for_user_addition(
                        db=db,
                        metrics=metrics,
                        user_list=added_users,
                        object_id=tag_id
                    )
    if removed_users:
        # Mark existing metrics as file_shared_to_ts
        deleted_timestamp = _parse_timestamp_utc(audit_log.get("timestamp"))

        # Update metrics for each associated tag
        for tag_id in tag_ids:
            await _update_metrics_for_user_removal(
                db=db,
                user_list=removed_users,
                deleted_timestamp=deleted_timestamp,
                object_id=tag_id
            )

    await db.commit()



async def update_shared_folder_metrics_for_tag_deletion(
        db: AsyncSession,
        audit_logs: List[Dict[str, str]]
     ):
    """
        Shared folder metrics for Tag Deletion .

        Args:
            db: Async database session
            audit_logs:
                List of audit log entries related to the shared folder action
    """
    deleted_timestamp = _parse_timestamp_utc(audit_logs[0].get("timestamp"))
    tag_id = _parse_int(audit_logs[0].get("object_key"))

    await db.execute(
            SharedFolderMetric.__table__
                .update()
                .where(
                    and_(
                        SharedFolderMetric.tag_id == tag_id,
                        SharedFolderMetric.file_shared_to_ts.is_(None)
                    )
                ).values(
                    file_shared_to_ts=deleted_timestamp
                )
            )
    await db.commit()


async def process_audit_logs_for_shared_folder_metrics(audit_logs: List[Dict[str, Any]]):
    """
    Process audit logs for shared folder metrics.
    """
    if not audit_logs:
        return

    async for session in get_session():
        try:
            first_action: str = audit_logs[0].get("action")
            prop = audit_logs[0].get("object_type")

            if prop == "database_release_tag":

                if first_action == "CREATE":
                    await create_shared_folder_metrics(
                        db=session,
                        audit_logs=audit_logs
                    )
                elif first_action  == "UPDATE" or first_action == "SYNC":
                    await update_shared_folder_metrics_for_tag_update(
                        db=session,
                        audit_logs=audit_logs
                    )
                elif first_action == "DELETE":
                    await update_shared_folder_metrics_for_tag_deletion(
                        db=session,
                        audit_logs=audit_logs
                    )
            else:
                for log in audit_logs:

                    object_property = log.get("object_property")
                    if first_action == "UPDATE" and object_property == "users":
                        await update_shared_folder_metrics_for_dl_update(
                            db=session,
                            audit_log=log
                        )
        except Exception:
            await session.rollback()
            return

