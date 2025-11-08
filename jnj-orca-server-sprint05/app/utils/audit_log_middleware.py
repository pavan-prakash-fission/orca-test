from fastapi import FastAPI, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.models import AuditLog, DistributionList, OutputDetail, DatabaseReleaseTag, DatabaseReleaseTagDistributionListLink, OutputDetailVersion
from sqlalchemy.sql import func 
import json
from typing import Any, Dict
from enum import Enum
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from app.config.settings import settings
from app.utils.sns_boto_client import send_audit_log
from app.utils.shared_folder_metrics import process_audit_logs_for_shared_folder_metrics


def to_serializable(value):
    if isinstance(value, Enum):
        return value.value  # store enum as its string value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode(errors="ignore")
    return value

async def get_m2m_data_for_tags(db, model, resource_id: int) -> dict:
    """Return many-to-many related data for DatabaseReleaseTag."""
    m2m_data = {}


    if model == DatabaseReleaseTag:
        # Output details
        result = await db.execute(
            select(
                OutputDetail.id,
                OutputDetailVersion.version_minor,
                OutputDetailVersion.version_major,
                OutputDetail.source_name
            )
            .join(OutputDetailVersion, OutputDetail.id == OutputDetailVersion.output_id)
            .where(
                OutputDetailVersion.tags.has_key(str(resource_id))  # HSTORE key check
            )
        )
        m2m_data["output_details"] = [{"id": row[0],"version": str(row[1])+'.'+str(row[2]),"source_name": row[3]}for row in result.fetchall()]
        
        # Distribution lists
        result = await db.execute(
            select(DistributionList.id)
            .join(DatabaseReleaseTagDistributionListLink)
            .where(DatabaseReleaseTagDistributionListLink.database_release_tag_id == resource_id)
        )
        m2m_data["distribution_lists"] = [row[0] for row in result.fetchall()]

    return m2m_data

async def audit_middleware(request: Request, call_next):

    if request.method in ("GET", "OPTIONS"):
        return await call_next(request)
    
    body_bytes = await request.body()
    
    # --- Capture basic request info ---
    path_parts = request.url.path.split("/")
    resource_type = path_parts[3] if len(path_parts) > 3 else None
    resource_id = None
    resource_ids  = []  # support multiple IDs for bulk actions

    try:
        resource_id = int(path_parts[4]) if len(path_parts) > 4 else None
    except ValueError:
        resource_id = None

    model = None
    if resource_type == "distribution-lists":
        model = DistributionList
    
    elif resource_type == "dbrs" and len(path_parts) > 4 and path_parts[4] == "tags":
        model = DatabaseReleaseTag
        if not resource_id and len(path_parts) > 5:
            try:
                resource_id = int(path_parts[5])
            except ValueError:
                resource_id = None  
    elif resource_type == "output-details" and len(path_parts) > 4 and path_parts[4] == "sync":
        model = DatabaseReleaseTag
        try:
            payload = json.loads(body_bytes.decode())
        except Exception:
            payload = {}
        resource_id = payload.get("tag_id")
    

    # --- Get OLD object data before processing ---
    old_data = None
    old_data_map = {}  # support multiple IDs
    if model and (resource_id or resource_ids):
        async for db in get_session():
            ids_to_fetch = resource_ids if resource_ids else ([resource_id] if resource_id else [])
            for resource_id in ids_to_fetch:
                old_obj = await db.get(model, resource_id)
                if old_obj:
                    old_data = {c.name: getattr(old_obj, c.name) for c in model.__table__.columns}
                    # --- Include many-to-many fields ---
                    m2m_data = await get_m2m_data_for_tags(db, model, resource_id)
                    old_data.update(m2m_data)
                    old_data_map[resource_id] = old_data
            break 
    # --- Proceed with the request ---
    response = await call_next(request)
    if response.status_code not in (200, 201, 202, 204):
        return response
    

    # --- Special handling for DOWNLOAD action ---
    # Example URL: /api/v1/download/
    if "download" in request.url.path and request.method == "POST":

        try:
            payload = json.loads(body_bytes.decode())
        except Exception:
            payload = {}

        file_ids = payload.get("file_ids", [])
        tag_id = payload.get("tag_id", None)
        timestamp = datetime.now(timezone.utc).isoformat()
        audit_logs = []
        object_type = None
        if file_ids:
            async for db in get_session():
                for file_id in file_ids:
                    file_obj = await db.get(OutputDetail, file_id)
                    if file_obj:
                        file_path = getattr(file_obj, "file_path", None)
                        if file_obj.reporting_effort_id:
                            object_type = "RE_output_details"
                        elif file_obj.database_release_id:
                            object_type = "DBR_output_details"
                        elif file_obj.study_id:
                            object_type = "STUDY_output_details"
                        elif file_obj.compound_id:
                            object_type = "COMPOUND_output_details"
                        else:
                            object_type = "output_details"
                        if tag_id:
                            result = await db.execute(
                                select(OutputDetailVersion)
                                .where(
                                    OutputDetailVersion.output_id == file_id,
                                    OutputDetailVersion.tags.has_key(str(tag_id))
                                )
                                )
                        else:
                            result = await db.execute(
                                select(OutputDetailVersion)
                                .where(
                                    OutputDetailVersion.output_id == file_id,
                                    OutputDetailVersion.is_latest == True)
                                )
                                
                        version_with_tag = result.scalar_one_or_none()
                        audit_logs.append({
                            "user_name": request.headers.get("X-User", "system"),
                            "action": "DOWNLOAD",
                            "timestamp": timestamp,
                            "object_type": object_type,
                            "object_key": str(file_id),
                            "object_property": "file_path",
                            "old_value": version_with_tag.file_path if version_with_tag else None,
                            "new_value": version_with_tag.file_path if version_with_tag else None,
                            "programming_plan_id": request.headers.get("X-Program-Id")
                        })
                break

        # Save logs
        if audit_logs:
            if settings.environment == "production":
                send_audit_log(audit_logs)
            else:
                async for db in get_session():
                    for entry in audit_logs:
                        db.add(AuditLog(**entry))
                    await db.commit()
                    break

        # Continue request processing
        return response


    
    if not model:
        return response


    if not resource_id and not resource_ids:
        # Capture streamed response safely
        if hasattr(response, "body_iterator"):
            response_body = b"".join([chunk async for chunk in response.body_iterator])

            async def new_body_iterator():
                yield response_body
            response.body_iterator = new_body_iterator()
        else:
            response_body = getattr(response, "body", b"")

        try:
            response_data = json.loads(response_body.decode())
        except Exception:
            response_data = {}

        # To get resource_id for newly created resources
        resource_id = response_data.get("id")
        
    # --- Determine ACTION based on method ---
    action_map = {"POST": "CREATE", "PUT": "UPDATE", "PATCH": "UPDATE", "DELETE": "DELETE"}
    action = action_map.get(request.method, "UNKNOWN")

    # --- override for URLs containing "records" ---
    if "records" in request.url.path:
        action = "UPDATE"
    elif "output-details/sync" in request.url.path:
        action = "SYNC"
    
    # --- Get NEW object data (after commit) ---
    new_data = None
    new_data_map = {}
    if model  and action in ["UPDATE", "CREATE", "SYNC"]:
        async for db in get_session():
            ids_to_fetch = resource_ids if resource_ids else ([resource_id] if resource_id else [])
            for resource_id in ids_to_fetch:
                new_obj = await db.get(model, resource_id)
                if new_obj:
                    new_data = {c.name: getattr(new_obj, c.name) for c in model.__table__.columns}
                    m2m_data = await get_m2m_data_for_tags(db, model, resource_id)
                    new_data.update(m2m_data)
                    new_data_map[resource_id] = new_data
            break
    
    # --- Compare and build per-field changes ---
    audit_logs = []
    timestamp = datetime.now(timezone.utc).isoformat()

    if action in ("CREATE", "UPDATE", "SYNC"):
        ids_to_log = resource_ids if resource_ids else ([resource_id] if resource_id else [])
        for resource_id in ids_to_log:
            old_data = old_data_map.get(resource_id, {})
            new_data = new_data_map.get(resource_id, {})
            all_fields = set((old_data or {}).keys()) | set((new_data or {}).keys())
            for field in all_fields:
                old_val = (old_data or {}).get(field)
                new_val = (new_data or {}).get(field)
                if str(old_val) != str(new_val):  # changed or newly created/deleted
                    audit_logs.append({
                        "user_name": request.headers.get("X-User", "system"),
                        "action": action,
                        "timestamp": timestamp,
                        "object_type": model.__tablename__ if model else "unknown",
                        "object_key": str(resource_id) if resource_id else None,
                        "object_property": field,
                        "old_value": json.dumps(old_val, default=to_serializable) if old_val is not None else None,
                        "new_value": json.dumps(new_val, default=to_serializable) if new_val is not None else None,
                        "programming_plan_id": request.headers.get("X-Program-Id"),  # optional
                    })

    elif action == "DELETE":
        # for field, new_val in new_data.items():
            audit_logs.append({
                "user_name": request.headers.get("X-User", "system"),
                "action": action,
                "timestamp": timestamp,
                "object_type": model.__tablename__ if model else "unknown",
                "object_key": str(resource_id) if resource_id else None,
                "object_property": None,
                "old_value": json.dumps(old_data, default=to_serializable) if old_data is not None else None,
                "new_value": json.dumps(new_data, default=to_serializable) if new_data is not None else None,
                "programming_plan_id": request.headers.get("X-Program-Id"),  # optional
            })

    # --- Save logs based on environment ---
    if audit_logs:
        if settings.environment == "production":
            # Send to SQS
            send_audit_log(audit_logs)
        else:
            # Store in DB
            async for db in get_session():
                for entry in audit_logs:
                    db.add(AuditLog(**entry))
                await db.commit()
                break
        # --- Process shared folder metrics ---
        try:
            obj_types = audit_logs[0].get("object_type")
            if obj_types == "database_release_tag" or obj_types == "distribution_lists":
                await process_audit_logs_for_shared_folder_metrics(audit_logs)
        except Exception as e:
            pass

    return response