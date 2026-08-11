"""Pydantic v2 schemas for the auth domain (API edge DTOs).

Secrets (password, PIN, hashes) are accepted as input but never returned:
no output schema contains a password/hash field.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.common.security import Role


class RegisterRequest(BaseModel):
    """Merchant onboarding: creates a Business and its first OWNER user."""

    business_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    contact_number: str = Field(min_length=3, max_length=20)
    address: str = Field(min_length=1, max_length=500)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """Safe user projection - no password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    email: EmailStr
    role: Role
    is_active: bool


class UserCreate(BaseModel):
    """OWNER creates an additional user within its own business."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.EMPLOYEE


class RegisterResponse(BaseModel):
    user: UserOut
    business_id: int
    tokens: TokenPair
