from sqlmodel import SQLModel
from typing import List, Optional

# Request schema for creating a DatabaseRelease
class DatabaseReleaseCreate(SQLModel):
    name: str
    study_id: int

# Request schema for updating a DatabaseRelease
class DatabaseReleaseUpdate(SQLModel):
    name: Optional[str] = None
    study_id: Optional[int] = None

# Response schema
class DatabaseReleaseResponse(SQLModel):
    id: int
    name: str
    study_id: int
 