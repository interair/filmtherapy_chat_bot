from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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


class EventCreate(BaseModel):
    """DTO for creating Event instances."""
    title: str = Field(..., min_length=1)
    when: datetime
    place: str = Field(..., min_length=1)
    price: Optional[float] = None
    description: Optional[str] = None

    class Config:
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


class ScheduleRule(BaseModel):
    """Typed schedule rule stored in Firestore.
    Document id is a deterministic composite key: f"{date}|{start}|{location}|{session_type}".
    date uses dd-mm-yy, time uses HH:MM.
    """
    id: Optional[str] = None
    date: str
    start: str
    end: str
    duration: int = 50
    interval: Optional[int] = None
    location: Optional[str] = ""
    session_type: Optional[str] = ""
    deleted: bool = False

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        s = str(v).strip()
        try:
            datetime.strptime(s, "%d-%m-%y")
        except Exception:
            raise ValueError("date must be in dd-mm-yy format")
        return s

    @staticmethod
    def _valid_hhmm(s: str) -> bool:
        try:
            parts = str(s).split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return 0 <= h <= 23 and 0 <= m <= 59
        except Exception:
            return False

    @field_validator("start", "end")
    @classmethod
    def _validate_hhmm(cls, v: str) -> str:
        s = str(v).strip()
        if not cls._valid_hhmm(s):
            raise ValueError("time must be in HH:MM format")
        return s

    @field_validator("duration", mode="before")
    @classmethod
    def _validate_duration(cls, v):
        try:
            return int(v)
        except Exception:
            return 50

    @field_validator("interval", mode="before")
    @classmethod
    def _validate_interval(cls, v, info):
        # if not provided, will be set to duration in model_validator
        if v is None or str(v).strip() == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    @model_validator(mode="after")
    def _post(self):
        # Default interval to duration
        if self.interval is None or int(self.interval) <= 0:
            object.__setattr__(self, "interval", int(self.duration))
        # Normalize strings
        loc = (self.location or "").strip()
        sess = (self.session_type or "").strip()
        object.__setattr__(self, "location", loc)
        object.__setattr__(self, "session_type", sess)
        # Ensure id
        if not self.id or not str(self.id).strip():
            doc_id = f"{self.date}|{self.start}|{loc}|{sess}"
            object.__setattr__(self, "id", doc_id)
        return self

    class Config:
        populate_by_name = True
        str_strip_whitespace = True
