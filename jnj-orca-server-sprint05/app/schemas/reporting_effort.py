from sqlmodel import SQLModel
from typing import List, Optional

# Request schema for creating a ReportingEffort
class ReportingEffortCreate(SQLModel):
    name: str
    database_release_id: int

# Request schema for updating a ReportingEffort
class ReportingEffortUpdate(SQLModel):
    name: Optional[str] = None
    database_release_id: Optional[int] = None

# Response schema
class ReportingEffortResponse(SQLModel):
    id: int
    name: str
    database_release_id: int
  