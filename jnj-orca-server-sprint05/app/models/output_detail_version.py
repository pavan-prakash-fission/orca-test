from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import  String, BigInteger, Float, Boolean, text, DateTime
from sqlalchemy.dialects.postgresql import HSTORE
from datetime import datetime, timezone




class OutputDetailVersion(SQLModel, table=True):
    __tablename__ = "output_detail_versions"

    id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    output_id: int = Field(foreign_key="output_details.id", nullable=False)
    version_major: int = Field(default=0,sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    version_minor: int = Field(default=0,sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    version_patch: int = Field(default=0,sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    file_path: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    file_size: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    is_latest: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default="true"))
    tags: dict = Field(default={}, sa_column=Column(HSTORE, nullable=False, index=True))
    orca_created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # UTC-aware datetime
        sa_column=Column(DateTime(timezone=True), nullable=False)
        )
    space_created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # UTC-aware datetime
        sa_column=Column(DateTime(timezone=True), nullable=False)
        )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # UTC-aware datetime
        sa_column=Column(DateTime(timezone=True), nullable=False)
        )

    output_detail: Optional["OutputDetail"] = Relationship(back_populates="versions")
 