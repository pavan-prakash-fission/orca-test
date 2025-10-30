from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING


if TYPE_CHECKING:  # avoid circular imports at runtime
    from app.models.compound import Compound

class Source(SQLModel, table=True):
    __tablename__ = "source"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, max_length=8)

    # --- Relationships ---
    compounds: List["Compound"] = Relationship(back_populates="source")
    tags: List["ReportingEffortTag"] = Relationship(back_populates="source")
    database_release_tags: List["DatabaseReleaseTag"] = Relationship(back_populates="source")
    output_details: List["OutputDetail"] = Relationship(back_populates="source")
    
   