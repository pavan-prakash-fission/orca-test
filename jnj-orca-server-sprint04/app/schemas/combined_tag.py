from typing import List, Union
from sqlmodel import SQLModel
from app.schemas.dbr_tag import BasicDatabaseReleaseTagResponse  
from app.schemas.tag import BasicReportingEffortTagResponse
from fastapi_pagination.cursor import CursorPage


class CombinedTagResponse(SQLModel):
    level: str
    tags: Union[
        List[BasicDatabaseReleaseTagResponse],
        CursorPage[BasicReportingEffortTagResponse]
    ]