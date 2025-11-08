from typing import Optional, List
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship, Column, UniqueConstraint
from sqlalchemy import String, DateTime, ARRAY
from app.models.associations import DatabaseReleaseTagDistributionListLink


class DistributionList(SQLModel, table=True):
    __tablename__ = "distribution_lists"
    __table_args__ = (
        UniqueConstraint("name", "study_id", name="_distributionlist_name_study_uc"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False)
    study_id: int = Field(foreign_key="study.id", nullable=False)

    co_owners: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String), nullable=False, default=[])
    )
    users: List[str] = Field(
        sa_column=Column(ARRAY(String), nullable=False)
    )

    created_by: str = Field(max_length=100, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_by: Optional[str] = Field(default=None, max_length=100, nullable=True)
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    study: Optional["Study"] = Relationship(back_populates="distribution_lists")
    database_release_tags: List["DatabaseReleaseTag"] = Relationship(
        back_populates="distribution_lists",
        link_model=DatabaseReleaseTagDistributionListLink,
    )