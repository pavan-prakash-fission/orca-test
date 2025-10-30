from pydantic import BaseModel, Field
from typing import List, Literal

class ImportTagsResponse(BaseModel):
    status: Literal['success', 'partial_success', 'failure'] = Field(..., description="Overall status of the import operation")
    unlinked_files: List[str] = Field(default_factory=list, description="List of file identifiers that could not be linked to tag")
    unregistered_users: List[str] = Field(default_factory=list, description="List of user emails that are not registered in the system")
    unregistered_user_lists: List[str] = Field(default_factory=list, description="List of distribution list names that are not registered in the system")