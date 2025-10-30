from pydantic import BaseModel, Field
from typing import List, Literal

class InputFileBatch(BaseModel):
    file_ids: List[int] = Field(..., description="List of file ids")
    source: Literal['PROD', 'PREPROD'] = Field(...,description="Source setting")
