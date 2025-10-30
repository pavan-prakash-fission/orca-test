from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class Study(SQLModel, table=True):
    __tablename__ = "study"
    __table_args__ = (UniqueConstraint("name", "compound_id", name="_study_name_compound_uc"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200, nullable=False)
    compound_id: int = Field(foreign_key="compound.id", nullable=False)

    compound: Optional["Compound"] = Relationship(back_populates="studies")
    database_releases: List["DatabaseRelease"] = Relationship(back_populates="study")
    output_details: List["OutputDetail"] = Relationship(back_populates="study")