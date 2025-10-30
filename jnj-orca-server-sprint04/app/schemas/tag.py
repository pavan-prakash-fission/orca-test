import re
from typing import Optional, List, Annotated
from pydantic import BaseModel, Field, field_validator
from sqlmodel import SQLModel
from app.utils.enums import ReasonEnum
from app.schemas.distribution_list import DistributionListResponse
from pydantic import model_validator
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


class ReportingEffortTagBase(SQLModel):
    tag_name: str
    reason: ReasonEnum
    users: List[str] = Field(default_factory=list)  
    distribution_list_ids: List[int] = Field(default_factory=list)

   

class ReportingEffortTagCreate(ReportingEffortTagBase):
    output_ids: Annotated[List[int], Field(min_length=1)]
    reporting_effort_id: int

    @field_validator("tag_name")
    def validate_tag_name(cls, v: str) -> str:
        return validate_tag_name_value(v)

    @model_validator(mode="after")
    def validate_lists(self) -> "ReportingEffortTagCreate":
        validate_users_or_distribution_list_ids(self.users, self.distribution_list_ids)
        return self

    


class ReportingEffortTagUpdate(ReportingEffortTagBase):
    output_ids: Optional[Annotated[List[int], Field(min_length=1)]] = None

    @field_validator("tag_name")
    def validate_tag_name(cls, v: str) -> str:
        return validate_tag_name_value(v)

    @model_validator(mode="after")
    def validate_lists(self) -> "ReportingEffortTagUpdate":
        validate_users_or_distribution_list_ids(self.users, self.distribution_list_ids)
        return self


class ReportingEffortTagResponse(ReportingEffortTagBase):
    id: int
    reporting_effort_id: int
    distribution_lists: List[DistributionListResponse] = []
    linked_output: List[OutputDetailRead] = Field(
        default_factory=list, alias="output_details"
    )
    reporting_effort_name:str= ""        

    class Config:
        from_attributes = True

class BasicReportingEffortTagResponse(SQLModel):
    id: int
    tag_name: str   

    class Config:
        from_attributes = True


class RecordRequest(SQLModel):
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