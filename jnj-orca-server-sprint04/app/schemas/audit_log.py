from sqlmodel import SQLModel
from typing import List, Optional


# Response schema
class AuditLogResponse(SQLModel):
    id: int
    user_name: Optional[str] = None
    action:Optional[str] = None
    timestamp:Optional[str] = None
    object_type:Optional[str] = None
    object_key:Optional[str] = None
    object_property:Optional[str] = None
    old_value:Optional[str] = None
    new_value:Optional[str] = None  
    programming_plan_id: Optional[int] = None
