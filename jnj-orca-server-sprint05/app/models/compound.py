from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

if TYPE_CHECKING:
    from app.models.source import Source
    from app.models.study import Study

class Compound(SQLModel, table=True):
    __tablename__ = "compound"
    __table_args__ = (UniqueConstraint("name", "source_id", name="_compound_name_source_uc"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False)
    source_id: int = Field(foreign_key="source.id", nullable=False)

    source: Optional["Source"] = Relationship(back_populates="compounds")
    studies: List["Study"] = Relationship(back_populates="compound")
    output_details: List["OutputDetail"] = Relationship(back_populates="compound")