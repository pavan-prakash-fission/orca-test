from typing import Optional, List, Set
from sqlalchemy import Column, Enum as SQLEnum , Index, func, String, ARRAY
from app.utils.enums import ReasonEnum
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, Column
from app.models.associations import ReportingEffortTagDistributionListLink, OutputDetailTagLink
from sqlalchemy.ext.mutable import MutableList


class ReportingEffortTag(SQLModel, table=True):
    __tablename__ = "reporting_effort_tag"

    id: Optional[int] = Field(default=None, primary_key=True, index=True)
    reporting_effort_id: Optional[int] = Field(
        default=None,
        foreign_key="reporting_effort.id",
        nullable=False
    )
    source_id: int = Field(foreign_key="source.id", nullable=True)
    tag_name: str = Field(sa_column=Column(String(255), nullable=False))
    reason: ReasonEnum = Field(
        sa_column=Column(SQLEnum(ReasonEnum, name="reasonenum"), nullable=False)
    )
    users: List[str] = Field(
        sa_column=Column(
            MutableList.as_mutable(ARRAY(String)),  # 👈 track mutations
            default=list,
            nullable=False
        ),
        default_factory=list
    )

    __table_args__ = (
        Index(
            "uq_reportingeffort_tag_lower",
            func.lower(Column("tag_name", String(100))),
            "reporting_effort_id",
            unique=True,
        ),
    )

    reporting_effort: "ReportingEffort" = Relationship(back_populates="tags")
    source: "Source" = Relationship(back_populates="tags")
    distribution_lists: List["DistributionList"] = Relationship(
        back_populates="tags",
        link_model=ReportingEffortTagDistributionListLink
    )
    output_details: List["OutputDetail"] = Relationship(
        back_populates="reporting_effort_tags",
        link_model=OutputDetailTagLink
    )

    def __repr__(self):
        return f"<ReportingEffortTag effort={self.reporting_effort_id} tag={self.tag_name}>"

    def get_all_users(self) -> Set[str]:
        """
        Returns all users (direct + from distribution lists)
        """
        all_users = set(self.users or [])
        for dl in self.distribution_lists:
            if dl.users:
                all_users.update(dl.users)
        return all_users