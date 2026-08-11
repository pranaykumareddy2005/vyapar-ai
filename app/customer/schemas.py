"""Pydantic schemas for the customer API edge (ORM never returned directly)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=3, max_length=20)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, min_length=3, max_length=20)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    name: str
    phone: str


class AddressCreate(BaseModel):
    line: str = Field(min_length=1, max_length=300)
    city: str = Field(min_length=1, max_length=100)
    pin: str = Field(min_length=3, max_length=12)


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    line: str
    city: str
    pin: str
