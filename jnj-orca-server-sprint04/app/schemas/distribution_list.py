from typing import Optional, List, Annotated
from datetime import datetime
from sqlmodel import SQLModel
from pydantic import Field


# Shared properties
class DistributionListBase(SQLModel):
    name: str
    co_owners: Annotated[List[str], Field(min_length=1)]
    users: Optional[Annotated[List[str], Field(min_length=1)]]



# Create schema (no id, no created_at)
class DistributionListCreate(DistributionListBase):
    pass


# Update schema (all optional)
class DistributionListUpdate(SQLModel):
    name: Optional[str] = None
    co_owners: Optional[List[str]] = None
    users: Optional[List[str]] = None


# Read schema (includes id + timestamps)
class DistributionListResponse(DistributionListBase):
    id: int
    created_by_id: int
    created_at: datetime
