"""
    OutputDetail schemas for create, update, and read operations.
"""
from datetime import datetime
from typing import Optional, List, Annotated
from sqlmodel import SQLModel
from fastapi import HTTPException
from pydantic import field_validator, Field


class OutputDetailBase(SQLModel):
    """
    Base schema for OutputDetail,
    representing the core attributes of an output detail.
    """
    identifier: Optional[str] = None
    title: Optional[str] = None
    reporting_effort_id: Optional[int] = None
    file_path: Optional[str] = None
    converted_file_path: Optional[str] = None
    created_at: Optional[datetime] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    is_out_of_sync: Optional[bool] = None


class OutputDetailBaseRequest(SQLModel):
    """
        Base schema for requests involving multiple OutputDetail records.
    """
    output_detail_ids: List[int]

    @field_validator("output_detail_ids")
    def validate_non_empty(cls, v):
        if not v:
            raise HTTPException(status_code=400, detail="No output detail IDs are provided.")
        return v


class OutputDetailSyncRequest(OutputDetailBaseRequest):
    """
        Schema for syncing multiple OutputDetail records with a source,
        extending the base request with an additional source attribute.
    """
    pass


class OutputDetailDeleteRequest(OutputDetailBaseRequest):
    """
        Schema for deleting multiple OutputDetail records,
        extending the base request with an additional reason attribute.
    """
    pass

class OutputDetailCreate(OutputDetailBase):
    pass


class OutputDetailUpdate(OutputDetailBase):
    pass


class OutputDetailRead(OutputDetailBase):
    """
        Schema for reading OutputDetail information,
        extending the base attributes with additional ID field.
    """
    id: Optional[int] = None


class OutputDetailWithTags(OutputDetailRead):
    """
        Schema for OutputDetail including associated tags,
        extending the base attributes with a list of related tags.
    """
    reporting_effort_tags: List[str] = []
    reporting_effort: Optional[str] = None
    database_release: Optional[str] = None
    study: Optional[str] = None
    compound: Optional[str] = None
    source: Optional[str] = None
    has_access: Optional[bool] = True
    docs_shared_as: Optional[str] = None


class UpdateDraftStatusRequest(SQLModel):
    output_ids: Annotated[List[int], Field(min_length=1)]


class BulkUpdateRequest(SQLModel):
    """Schema for bulk updating multiple OutputDetail records."""
    ids: List[int]
    data: OutputDetailUpdate
