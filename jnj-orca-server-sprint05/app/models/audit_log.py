from typing import Optional
from sqlalchemy import String
from sqlmodel import BigInteger, SQLModel, Field, Column

class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, index=True)
    )
    user_name: Optional[str] = Field(sa_column=Column(String(512), nullable=True))
    action: Optional[str] = Field(sa_column=Column(String(512), nullable=True))
    timestamp: Optional[str] = Field(sa_column=Column(String(356), nullable=True))
    object_type: Optional[str] = Field(sa_column=Column(String(512), nullable=True))
    object_key: Optional[str] = Field(sa_column=Column(String(512), nullable=True))
    object_property: Optional[str] = Field(sa_column=Column(String(512), nullable=True))
    old_value: Optional[str] = Field(sa_column=Column(String(2048), nullable=True))
    new_value: Optional[str] = Field(sa_column=Column(String(2048), nullable=True))
    programming_plan_id: Optional[int] = Field(sa_column=Column(BigInteger, nullable=True))