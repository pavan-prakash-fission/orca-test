from datetime import datetime, timezone
from app.models import AuditLog
from sqlalchemy.ext.asyncio import AsyncSession

async def create_audit_log(
    session: AsyncSession,
    user_name: str = None,
    action: str = None,
    object_type: str = None,
    object_key: str = None,
    object_property: str = None,
    old_value: str = None,
    new_value: str = None,
):
    log = AuditLog(
        user_name=user_name,
        action=action,
        timestamp=datetime.now(timezone.utc).isoformat(),
        object_type=object_type,
        object_key=object_key,
        object_property=object_property,
        old_value=old_value,
        new_value=new_value,
    )
    session.add(log)