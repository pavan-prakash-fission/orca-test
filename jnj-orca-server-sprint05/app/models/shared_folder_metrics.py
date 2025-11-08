"""
    Shared Folder Metrics Model
"""
from typing import Optional
from datetime import datetime

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import String, Text, DateTime, BigInteger, Integer


class SharedFolderMetric(SQLModel, table=True):
    """
        Shared Folder Metrics Model for tracking shared folder activities.
    """
    __tablename__ = "shared_folder_metrics"  # type: ignore

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True),
    )

    file_shared_to: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    compound: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    study: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    dbr: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    re: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )

    file_shared: Optional[str] = Field(
        default=None,
        sa_column=Column(String(2048), nullable=True),
    )
    file_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(512), nullable=True),
    )

    file_shared_from_ts: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    file_shared_to_ts: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    file_shared_by: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    to_folder_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )

    file_version_major: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    file_version_minor: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    file_version_patch: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )

    comment: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    external_share_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    external_share_file_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    external_folder_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )

    tag_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    tag_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    output_detail_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
