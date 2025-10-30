from sqlmodel import SQLModel
from typing import Optional
from typing import List

# Request schema for creating a new compound
class CompoundCreate(SQLModel):
    name: str
    source_id: int


# Request schema for updating a compound
class CompoundUpdate(SQLModel):
    name: Optional[str] = None
    source_id: Optional[int] = None


# Response schema (what we return in API)
class CompoundResponse(SQLModel):
    id: int
    name: str
    source_id: int
