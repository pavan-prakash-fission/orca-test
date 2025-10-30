from typing import Optional, List, Set
from sqlalchemy import Column, Enum as SQLEnum, Index, func
from sqlalchemy import UniqueConstraint
from app.utils.enums import ReasonEnum
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import String, DateTime, ARRAY
from app.models.associations import OutputDetailDatabaseReleaseTagLink, DatabaseReleaseTagDistributionListLink
from sqlalchemy.ext.mutable import MutableList


class DatabaseReleaseTag(SQLModel, table=True):
    __tablename__ = "database_release_tag"

    id: Optional[int] = Field(default=None, primary_key=True, index=True)
    database_release_id: Optional[int] = Field(
        default=None,
        foreign_key="database_release.id",
        nullable=False
    )
    source_id: int = Field(foreign_key="source.id", nullable=True)
    tag_name: str = Field(sa_column=Column(String(255), nullable=False))
    reason: ReasonEnum = Field(
        sa_column=Column(SQLEnum(ReasonEnum, name="reasonenum",create_type=False), nullable=False)
    )
    users: List[str] = Field(
        sa_column=Column(
            MutableList.as_mutable(ARRAY(String)),  #  track mutations
            default=list,
            nullable=False
        ),
        default_factory=list
    )

    __table_args__ = (
        Index(
            "uq_databaserelease_tag_lower",
            func.lower(Column("tag_name", String(100))),
            "database_release_id",
            unique=True,
        ),
    )

    database_release: "DatabaseRelease" = Relationship(back_populates="tags")
    source: "Source" = Relationship(back_populates="database_release_tags")
    distribution_lists: List["DistributionList"] = Relationship(
        back_populates="database_release_tags",
        link_model=DatabaseReleaseTagDistributionListLink
    )
    output_details: List["OutputDetail"] = Relationship(
        back_populates="database_release_tags",
        link_model=OutputDetailDatabaseReleaseTagLink
    )

    def __repr__(self):
        return f"<DatabaseReleaseTag release={self.database_release_id} tag={self.tag_name}>"

    def get_all_users(self) -> Set[str]:
        """
        Returns all users (direct + from distribution lists)
        """
        all_users = set(self.users or [])
        for dl in self.distribution_lists:
            if dl.users:
                all_users.update(dl.users)
        return all_users