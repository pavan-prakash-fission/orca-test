from sqlmodel import SQLModel, Field, Relationship, Column
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import DateTime



class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, nullable=False, max_length=150, unique=True)
    first_name: Optional[str] = Field(default=None, max_length=150)
    last_name: Optional[str] = Field(default=None, max_length=150)
    email: Optional[str] = Field(default=None, max_length=254)
    password: str = Field(nullable=False, max_length=256)  # store hashed password
    is_staff: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)
    last_login: Optional[datetime] = Field(default=None, nullable=True)
    date_joined: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),
    sa_column=Column(DateTime(timezone=True), nullable=False)  # important: timezone=True
    )
    role: str = Field(default="reviewer", max_length=50, nullable=False)

    # relation to DistributionList
    distribution_lists: List["DistributionList"] = Relationship(back_populates="created_by")
