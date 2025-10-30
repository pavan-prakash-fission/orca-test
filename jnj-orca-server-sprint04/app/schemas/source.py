from sqlmodel import SQLModel
from typing import List, Optional

# Request schema for creating a source
class SourceCreate(SQLModel):
    name: str


# Request schema for updating a source
class SourceUpdate(SQLModel):
    name: Optional[str] = None


# Response schema (what we return in API)
class SourceRead(SQLModel):
    id: int
    name: str

