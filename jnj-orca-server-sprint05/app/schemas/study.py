from sqlmodel import SQLModel
from typing import List, Optional

# Request schema for creating a Study
class StudyCreate(SQLModel):
    name: str
    compound_id: int

# Request schema for updating a Study
class StudyUpdate(SQLModel):
    name: Optional[str] = None
    compound_id: Optional[int] = None

# Response schema
class StudyResponse(SQLModel):
    id: int
    name: str
    compound_id: int
    