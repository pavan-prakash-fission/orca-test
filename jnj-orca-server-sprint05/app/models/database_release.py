from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint


class DatabaseRelease(SQLModel, table=True):
    __tablename__ = "database_release"
    __table_args__ = (UniqueConstraint("name", "study_id", name="_dbrelease_name_study_uc"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False)
    study_id: int = Field(foreign_key="study.id", nullable=False)

    study: Optional["Study"] = Relationship(back_populates="database_releases")
    reporting_efforts: List["ReportingEffort"] = Relationship(back_populates="database_release")
    tags: List["DatabaseReleaseTag"] = Relationship(back_populates="database_release")
    output_details: List["OutputDetail"] = Relationship(back_populates="database_release")