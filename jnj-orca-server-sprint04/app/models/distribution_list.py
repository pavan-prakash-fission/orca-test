from typing import Optional, List
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import String, DateTime, ARRAY
from app.models.associations import DatabaseReleaseTagDistributionListLink, ReportingEffortTagDistributionListLink




class DistributionList(SQLModel, table=True):
    __tablename__ = "distribution_lists"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False)

    co_owners: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String), nullable=False, default=[])
    )
    users: List[str] = Field(
        sa_column=Column(ARRAY(String), nullable=False)
    )

    created_by_id: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),  # UTC-aware datetime
    sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    created_by: "User" = Relationship(back_populates="distribution_lists")
    tags: List["ReportingEffortTag"] = Relationship(
        back_populates="distribution_lists",
        link_model=ReportingEffortTagDistributionListLink,
    )
    database_release_tags: List["DatabaseReleaseTag"] = Relationship(
    back_populates="distribution_lists",
    link_model=DatabaseReleaseTagDistributionListLink,
)