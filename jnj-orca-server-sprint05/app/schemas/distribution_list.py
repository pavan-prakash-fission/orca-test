from typing import Optional, List, Annotated
from datetime import datetime
from sqlmodel import SQLModel
from pydantic import Field


# Shared properties
class DistributionListBase(SQLModel):
    name: str
    study_id: int
    co_owners: Annotated[List[str], Field(min_length=1)]
    users: Optional[Annotated[List[str], Field(min_length=1)]]



# Create schema (no id, no created_at)
class DistributionListCreate(DistributionListBase):
    pass


# Update schema (all optional)
class DistributionListUpdate(DistributionListBase):
    pass


# Read schema (includes id, study_id, created_by, created_at)
class DistributionListResponse(DistributionListBase):
    id: int
    created_by: str
    created_at: datetime
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None 
    tags: str = ""
