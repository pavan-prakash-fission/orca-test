from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class InputFileBatch(BaseModel):
    file_ids: List[int] = Field(..., description="List of file ids")
    source: Literal['PROD', 'PREPROD', 'DOCS'] | None = Field(None, description="Source setting")

class TaggedOutputs(BaseModel):
    source_name: Literal['PROD', 'PREPROD', 'DOCS'] | None = Field(None, description="Source setting")
    compound_name: str = Field(..., description="Compound ID to filter files")
    study_name: str = Field(..., description="Study ID to filter files")
    dbr_name: str = Field(..., description="Database Release ID to filter files")
    tag_name: str = Field(..., description="Tag ID to filter files")
    file_name: Optional[str] = Field(None, description="Optional file name filter")