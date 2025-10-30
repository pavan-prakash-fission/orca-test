from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from pydantic import model_validator


class UserBase(SQLModel):
    username: str = Field(index=True, max_length=150)
    first_name: Optional[str] = Field(default=None, max_length=150)
    last_name: Optional[str] = Field(default=None, max_length=150)
    email: Optional[str] = Field(default=None, max_length=254)
    is_staff: bool = Field(default=False)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    role: str = Field(default="reviewer", max_length=50)

class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int
    date_joined: datetime
    last_login: Optional[datetime] = None
    fullName: Optional[str] = None
    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def set_full_name(self):
        self.fullName = f"{self.first_name} {self.last_name}".strip()
        return self


class UserUpdate(SQLModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None
    is_superuser: Optional[bool] = None
    role: Optional[str] = None


class LoginRequest(SQLModel):
    username: str
    password: Optional[str] = None

class LoginResponse(SQLModel):
    username: str
    role: str
    user_id: int
