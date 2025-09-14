from __future__ import annotations

from datetime import datetime
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


class SessionType(Enum):
    FACE_TO_FACE = "Очно"
    SAND_THERAPY = "Песочная терапия"
    ONLINE = "Онлайн"


class BookingStatus(Enum):
    PENDING = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Location(BaseModel):
    name: str = Field(..., min_length=1)


class Event(BaseModel):
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    when: datetime
    place: str = Field(..., min_length=1)
    price: Optional[float] = None
    description: Optional[str] = None
    photo: Optional[str] = None  # filename in data/ (served at /static/<filename>)

    class Config:
        # For Jinja2 compatibility, allow attribute-style access and JSON serialization
        populate_by_name = True
        str_strip_whitespace = True


class Booking(BaseModel):
    id: str = Field(..., min_length=1)
    user_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    slot_id: Optional[str] = None
    start: datetime
    end: datetime
    location: Optional[str] = None
    session_type: Optional[str] = None
    status: Optional[str] = None
    price: Optional[float] = None
    created_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        str_strip_whitespace = True
