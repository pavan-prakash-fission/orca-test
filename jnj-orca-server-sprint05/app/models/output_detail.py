from typing import List, Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import Boolean, String, DateTime, BigInteger, Text, Float, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import HSTORE
from sqlalchemy import Index
from app.models.associations import OutputDetailDatabaseReleaseTagLink
from app.utils.enums import DocsSharedAs


class OutputDetail(SQLModel, table=True):
    __tablename__ = "output_details"

    id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, primary_key=True, index=True))
    identifier: str = Field(sa_column=Column(String(255), nullable=False))
    title: str = Field(sa_column=Column(Text, nullable=False))

    # reporting_effort_id: int = Field(foreign_key="reporting_effort.id", nullable=False)
    reporting_effort_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("reporting_effort.id"), nullable=True))
    reporting_effort: "ReportingEffort" = Relationship(back_populates="output_details")

    file_path: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    file_type: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True, index=True))
    converted_file_path: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))

    created_at: datetime = Field(
        sa_column = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)   # make sure it's a callable
    )
    )
    file_size: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
   
    reporting_effort_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    database_release_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("database_release.id"), nullable=True))
    database_release: "DatabaseRelease" = Relationship(back_populates="output_details")
    database_release_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    study_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("study.id"), nullable=True))
    study: "Study" = Relationship(back_populates="output_details")
    study_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    compound_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("compound.id"), nullable=True))
    compound: "Compound" = Relationship(back_populates="output_details")
    compound_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    source_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, ForeignKey("source.id"), nullable=True))
    source: "Source" = Relationship(back_populates="output_details")
    source_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    tags: dict = Field(sa_column=Column(HSTORE, index=True))
    adr_filepath: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))
    orca_version: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    space_version: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    is_out_of_sync: Optional[bool] = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default="false"))
    docs_shared_as: Optional[DocsSharedAs] = Field(default=None,sa_column=Column(SQLEnum(DocsSharedAs, name="docs_shared_as_enum"),nullable=True))

    database_release_tags: List["DatabaseReleaseTag"] = Relationship(
    back_populates="output_details",
    link_model=OutputDetailDatabaseReleaseTagLink
    )
    versions: List["OutputDetailVersion"] = Relationship(back_populates="output_detail")
    

Index("ix_output_details_tags_gin", OutputDetail.tags, postgresql_using="gin")
