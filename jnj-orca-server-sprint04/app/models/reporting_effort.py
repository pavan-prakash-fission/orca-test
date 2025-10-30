from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint


class ReportingEffort(SQLModel, table=True):
    __tablename__ = "reporting_effort"
    __table_args__ = (UniqueConstraint("name", "database_release_id", name="_re_name_dbrel_uc"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, nullable=False)
    database_release_id: int = Field(foreign_key="database_release.id", nullable=False)

    # --- Relationships ---
    tags: List["ReportingEffortTag"] = Relationship(
        back_populates="reporting_effort"
    )

    output_details: List["OutputDetail"] = Relationship(
        back_populates="reporting_effort"
    )

    database_release: "DatabaseRelease" = Relationship(
        back_populates="reporting_efforts"
    )