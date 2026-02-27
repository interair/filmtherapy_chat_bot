
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class SessionType(Enum):
    FACE_TO_FACE = "Очно"
    SAND_THERAPY = "Песочная терапия"
    ONLINE = "Онлайн"


class BookingStatus(Enum):
    PENDING = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BaseConfigModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True
    )


class Location(BaseConfigModel):
    name: str = Field(..., min_length=1)


class Event(BaseConfigModel):
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    when: datetime
    place: str = Field(..., min_length=1)
    price: Optional[float] = None
    description: Optional[str] = None
    photo: Optional[str] = None  # filename in data/ (served at /static/<filename>)


class EventCreate(BaseConfigModel):
    """DTO for creating Event instances."""
    title: str = Field(..., min_length=1)
    when: datetime
    place: str = Field(..., min_length=1)
    price: Optional[float] = None
    description: Optional[str] = None
    photo: Optional[str] = None


class Booking(BaseConfigModel):
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
    comment: Optional[str] = None
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

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True
    )


class ScheduleRule(BaseConfigModel):
    """Typed schedule rule stored in Firestore.
    Document id is a deterministic composite key: f"{day_of_week}|{start}|{location}|{session_type}".
    day_of_week is 0-6 (0=Mon, 6=Sun), time uses HH:MM.
    """
    id: Optional[str] = None
    day_of_week: int = Field(..., ge=0, le=6)
    start: str
    end: str
    duration: int = 50
    interval: Optional[int] = None
    location: Optional[str] = ""
    session_type: Optional[str] = ""
    deleted: bool = False

    @field_validator("day_of_week", mode="before")
    @classmethod
    def _validate_day_of_week(cls, v) -> int:
        try:
            val = int(v)
            if 0 <= val <= 6:
                return val
            raise ValueError("day_of_week must be between 0 and 6")
        except (ValueError, TypeError):
            raise ValueError("day_of_week must be an integer between 0 and 6")

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
            doc_id = f"{self.day_of_week}|{self.start}|{loc}|{sess}"
            object.__setattr__(self, "id", doc_id)
        return self
