import re
from typing import Optional, List, Annotated
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import SQLModel
from app.utils.enums import ReasonEnum
from app.schemas.distribution_list import DistributionListResponse
from app.schemas.output_detail import OutputDetailRead  

def validate_tag_name_value(v: str) -> str:
    v = v.strip()
    # length check after stripping
    if len(v) < 3 or len(v) > 255:
        raise ValueError("Tag name must be between 3 and 255 characters (excluding spaces).")
    
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", v):
        raise ValueError(
            "Please enter a valid Tag Name. Only letters, numbers, underscores (_), hyphens (-), and periods (.) are allowed. No spaces allowed."
        )
    return v

def validate_users_or_distribution_list_ids(users: List[str], distribution_list_ids: List[int]) -> None:
    if not users and not distribution_list_ids:
        raise ValueError("Either 'users' or 'distribution_list_ids' must contain at least one value.")

class DatabaseReleaseTagBase(SQLModel):
    tag_name: str
    reason: ReasonEnum
    users: List[str] = Field(default_factory=list)  
    distribution_list_ids: List[int] = Field(default_factory=list)
    
   

class DatabaseReleaseTagCreate(DatabaseReleaseTagBase):
    output_ids: Annotated[List[int], Field(min_length=1)]
    database_release_id: int
    identify_as_draft: Optional[bool] = False

    @field_validator("tag_name")
    def validate_tag_name(cls, v: str) -> str:
        return validate_tag_name_value(v) 
    
    @model_validator(mode="after")
    def validate_lists(self) -> "DatabaseReleaseTagCreate":
        validate_users_or_distribution_list_ids(self.users, self.distribution_list_ids)
        return self


class DatabaseReleaseTagUpdate(DatabaseReleaseTagBase):
    output_ids: Optional[Annotated[List[int], Field(min_length=1)]] = None

    @field_validator("tag_name")
    def validate_tag_name(cls, v: str) -> str:
        return validate_tag_name_value(v)
    
    @model_validator(mode="after")
    def validate_lists(self) -> "DatabaseReleaseTagUpdate":
        validate_users_or_distribution_list_ids(self.users, self.distribution_list_ids)
        return self


class DatabaseReleaseTagResponse(DatabaseReleaseTagBase):
    id: int
    database_release_id: int
    distribution_lists: List[DistributionListResponse] = []
    linked_output: List[OutputDetailRead] = Field(
        default_factory=list, alias="output_details"
    )
    database_release_name:str= ""
            

    class Config:
        from_attributes = True

class BasicDatabaseReleaseTagResponse(SQLModel):
    id: int
    tag_name: str   

    class Config:
        from_attributes = True


class AddRecordRequest(SQLModel):
    record_ids: Annotated[List[int], Field(min_length=1)]
    identify_as_draft: Optional[bool] = False

class RemoveRecordRequest(SQLModel):
    record_ids: Annotated[List[int], Field(min_length=1)]


# Response schema
class AddRecordResponse(SQLModel):
    message: str
    tag_name: str
    added_records: Optional[List[str]] = []
    already_added_records: Optional[List[str]] = []

class RemoveRecordResponse(SQLModel):
    message: str
    tag_id: int
    tag_name: str
    removed_records: Optional[List[str]] = []
    not_associated_records: Optional[List[int]] = []