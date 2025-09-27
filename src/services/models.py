from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


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
    session_type: Optional[SessionType] = None
    status: Optional[BookingStatus] = None
    price: Optional[float] = None
    created_at: Optional[datetime] = None

    # Shared enum coercion for validators
    @classmethod
    def _coerce_enum(cls, v, enum_cls: type[Enum], field_name: str):
        # Allow passing through None or already-correct enum
        if v is None or isinstance(v, enum_cls):
            return v
        try:
            s = str(v).strip()
        except (ValueError, TypeError):
            logger.error("Invalid %s value: %r", field_name, v, exc_info=True)
            return None
        # Match by value or by enum name (case-insensitive)
        for item in enum_cls:
            if s == item.value or s.lower() == item.name.lower():
                return item
        return None

    # Coerce incoming strings into enums and allow None
    @field_validator("session_type", mode="before")
    @classmethod
    def _validate_session_type(cls, v):
        return cls._coerce_enum(v, SessionType, "session_type")

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, v):
        return cls._coerce_enum(v, BookingStatus, "status")

    class Config:
        populate_by_name = True
        str_strip_whitespace = True
        use_enum_values = True
