from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pydantic
from fastapi import UploadFile

from ...container import container
from ...services.calendar_service import CalendarService

logger = logging.getLogger(__name__)

class BookingView(pydantic.BaseModel):
    id: str = ""
    location: str = "Unknown"
    session_type: str = "Unknown"
    user_name: str = "Unknown"
    user_id: str = "Unknown"
    status: str = "Unknown"
    status_color: str = "orange"
    date_str: str = "Unknown"
    time_str: str = "Unknown"
    created_at: str = "Unknown"

    @classmethod
    def from_raw(cls, booking: dict) -> "BookingView":
        status = booking.get('status', 'Unknown')
        status_color = "green" if status == 'confirmed' else "orange"
        user_name = booking.get('name') or ''
        try:
            user_name_safe = str(user_name) if user_name else 'Unknown'
        except (ValueError, TypeError):
            user_name_safe = 'Unknown'
        
        start_iso = booking.get('start')
        date_str = 'Unknown'
        time_str = 'Unknown'
        if isinstance(start_iso, str) and 'T' in start_iso:
            parts = start_iso.split('T', 1)
            date_str = parts[0]
            time_str = parts[1][:5]
            
        return cls(
            id=str(booking.get('id', '') or ''),
            location=str(booking.get('location', 'Unknown') or 'Unknown'),
            session_type=str(booking.get('session_type', 'Unknown') or 'Unknown'),
            user_name=user_name_safe,
            user_id=str(booking.get('user_id', 'Unknown') or 'Unknown'),
            status=str(status),
            status_color=status_color,
            date_str=date_str,
            time_str=time_str,
            created_at=str(booking.get('created_at', 'Unknown') or 'Unknown'),
        )

    @classmethod
    def list_from_raw(cls, items: list[dict] | None) -> list["BookingView"]:
        return [cls.from_raw(b or {}) for b in (items or [])]

def parse_title_code_lines(text: str) -> list[dict]:
    items: list[dict] = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            title, code = line.split("|", 1)
        else:
            title, code = line, line.lower().replace(" ", "_")
        title = title.strip()
        code = code.strip()
        if title and code:
            items.append({"title": title, "code": code})
    return items

async def save_upload(
    file_field: UploadFile,
    dst_dir: Path,
    allowed_exts: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp"),
) -> str | None:
    if not file_field or not file_field.filename:
        return None
    ext = Path(file_field.filename).suffix.lower()
    if ext not in allowed_exts:
        ext = ".jpg"
    
    name = f"{secrets.token_hex(8)}{ext}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    path = dst_dir / name
    
    try:
        content = await file_field.read()
        path.write_bytes(content)
        return name
    except Exception:
        logger.exception("Failed to save upload")
        return None

async def compute_new_bookings_today(
    bookings: Optional[list[dict]] = None,
    now: Optional[datetime] = None,
    calendar_service: Optional[CalendarService] = None,
) -> int:
    new_bookings_today = 0
    try:
        if bookings is None:
            svc = calendar_service or container.calendar_service()
            raw_bookings = await svc.list_all_bookings()
        else:
            raw_bookings = bookings
        
        if raw_bookings:
            today_utc = ((now or datetime.now(timezone.utc)).date())
            for b in raw_bookings:
                created = b.get('created_at') or b.get('created')
                if isinstance(created, str) and created:
                    try:
                        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        d_utc = (dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date())
                        if d_utc == today_utc:
                            new_bookings_today += 1
                    except Exception:
                        continue
    except Exception:
        logger.exception("Failed to compute new bookings today")
    return new_bookings_today
