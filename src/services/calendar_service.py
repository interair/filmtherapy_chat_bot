from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .repositories import BookingRepository, ScheduleRepository
from ..exceptions import ValidationError

logger = logging.getLogger(__name__)

LOCATIONS = [
    "IJsbaanpad 9",
    "Van Eeghenlaan 27",
    "Binnenkant 24",
]

@dataclass
class Slot:
    id: str
    start: datetime
    end: datetime
    location: Optional[str]
    session_type: str


class CalendarService:
    """Booking service using Firestore for bookings and schedule.
    """

    def __init__(
        self,
        bookings_repo: BookingRepository,
        schedule_repo: ScheduleRepository,
    ) -> None:
        if bookings_repo is None or schedule_repo is None:
            raise ValueError("CalendarService requires repositories to be provided via DI")
        self._bookings_repo = bookings_repo
        self._schedule_repo = schedule_repo

    # --- Helpers -----------------------------------------------------
    @staticmethod
    def parse_hhmm(val: str) -> Optional[tuple[int, int]]:
        """Parse time in HH:MM format and return (hour, minute) or None."""
        try:
            parts = str(val).split(":")
            h = int(parts[0])
            m = int(parts[1] if len(parts) > 1 else 0)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
            return None
        except Exception:
            logger.debug("parse_hhmm: invalid value %r", val, exc_info=True)
            return None

    @staticmethod
    def ensure_utc(dt: datetime) -> datetime:
        """Return timezone-aware datetime in UTC without changing the wall time if tzinfo is missing."""
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def normalize_session_type(val: Optional[str]) -> str:
        """Normalize labels to canonical keys used in matching.
        Returns one of: 'any' | 'online' | 'offline' | 'sand' | 'rest'.
        Notes:
        - 'any' means wildcard (matches any selected type).
        - 'sand' is a subtype of in-person and is treated as 'offline' during matching.
        - If value is empty/unknown, default to 'offline' (in-person).
        """
        s = (val or "").strip().lower()
        if not s:
            return "offline"
        # Explicit wildcard support (EN/RU synonyms)
        if any(k in s for k in ("any", "both", "оба", "любой", "все")):
            return "any"
        if any(k in s for k in ("online", "онлайн")):
            return "online"
        if any(k in s for k in ("rest", "осталь")):
            return "rest"
        if any(k in s for k in ("sand", "песоч")):
            return "sand"
        # Explicit offline synonyms
        if any(k in s for k in ("offline", "офлайн", "оффлайн", "очно")):
            return "offline"
        # Fallback: anything else treated as in-person
        return "offline"

    @staticmethod
    def normalize_location_rule(val: Optional[str]) -> str:
        """Normalize schedule 'location' rule value.
        Returns one of:
        - 'any' → wildcard: applies to any physical location AND to online
        - 'online' → applies to online appointments only
        - '<exact>' → a concrete location string (case-sensitive kept as original trimmed)
        """
        raw = (val or "").strip()
        s = raw.lower()
        if not s:
            return "any"
        if any(k in s for k in ("any", "both", "оба", "любой", "все")):
            return "any"
        if any(k in s for k in ("online", "онлайн")):
            return "online"
        return raw

    def _day_busy_intervals(self, date: datetime) -> list[tuple[datetime, datetime]]:
        """Collect busy intervals for the given date by querying Firestore, avoiding full collection scans."""
        from_iso = datetime.fromisoformat
        rep = self._bookings_repo
        busy: list[tuple[datetime, datetime]] = []
        for b in rep.get_for_date_sync(date):
            try:
                s_s = b.get("start")
                e_s = b.get("end")
                if not (isinstance(s_s, str) and isinstance(e_s, str)):
                    continue
                s_dt = self.ensure_utc(from_iso(s_s.replace("Z", "+00:00")))
                e_dt = self.ensure_utc(from_iso(e_s.replace("Z", "+00:00")))
                busy.append((s_dt, e_dt))
            except Exception:
                logger.debug("_day_busy_intervals: skip invalid booking record: %r", b, exc_info=True)
                continue
        return busy

    # --- Matching helpers (to keep logic in one place) -----------------------
    def _match_rule(self, date: datetime, rule: dict, sel_loc: str, norm_in: str) -> Optional[tuple[datetime, datetime, int, int, str]]:
        """Return (window_start, window_end, duration_min, interval_min, r_loc_norm) if the rule applies, else None.
        Simplifies matching by handling date (dd-mm-yy), location, type, and time window.
        """
        try:
            rule_date = str(rule.get("date") or "").strip()
            if not rule_date:
                return None
            # Compare against provided date in dd-mm-yy format
            if rule_date != date.strftime("%d-%m-%y"):
                return None
        except Exception:
            return None

        r_loc_norm = self.normalize_location_rule(str(rule.get("location") or "").strip())
        is_online_session = norm_in == "online"
        if r_loc_norm == "online":
            if not is_online_session:
                return None
        elif r_loc_norm != "any":
            # Specific physical location: for offline sessions require equality
            if not is_online_session and sel_loc and sel_loc != r_loc_norm:
                return None

        r_sess = str(rule.get("session_type") or "").strip()
        if r_sess:
            norm_rule_raw = self.normalize_session_type(r_sess)
            if norm_rule_raw == "rest":
                return None
            norm_rule = "offline" if norm_rule_raw in ("sand", "offline") else norm_rule_raw
            if norm_rule not in ("", "any"):
                if norm_rule == "online" and norm_in != "online":
                    return None
                if norm_rule == "offline" and norm_in == "online":
                    return None
                if norm_rule not in ("online", "offline") and norm_rule != norm_in:
                    return None

        p_start = self.parse_hhmm(str(rule.get("start", "")).strip())
        p_end = self.parse_hhmm(str(rule.get("end", "")).strip())
        if not p_start and not p_end:
            p_start, p_end = (0, 0), (23, 59)
        if not (p_start and p_end):
            return None

        try:
            duration_min = int(rule.get("duration", 50) or 50)
            interval_min = int(rule.get("interval", duration_min) or duration_min)
        except Exception:
            duration_min = 50
            interval_min = 50

        window_start = datetime(date.year, date.month, date.day, p_start[0], p_start[1], tzinfo=timezone.utc)
        window_end = datetime(date.year, date.month, date.day, p_end[0], p_end[1], tzinfo=timezone.utc)
        if window_start >= window_end:
            return None
        return window_start, window_end, duration_min, interval_min, r_loc_norm

    def iter_free_slots(self, window_start: datetime, window_end: datetime, duration_min: int, interval_min: int, busy_intervals: list[tuple[datetime, datetime]], now_utc: datetime):
        """Yield (start, end) for each free slot within the window.
        Assumes timezone-aware datetimes.
        """
        cur = window_start
        dur = timedelta(minutes=duration_min)
        step = timedelta(minutes=interval_min)
        while cur + dur <= window_end:
            slot_start = cur
            slot_end = slot_start + dur
            if slot_end > now_utc and all(not self.overlaps(slot_start, slot_end, b0, b1) for b0, b1 in busy_intervals):
                yield slot_start, slot_end
            cur += step

    def list_available_slots(
        self, date: datetime, location: Optional[str], session_type: str
    ) -> List[Slot]:
        # Build slots from recurrent schedule rules (from Firestore), avoid full bookings reload
        cfg = self._schedule_repo.get_sync()
        rules = cfg.get("rules", []) if isinstance(cfg, dict) else []
        
        # Ensure the input date is timezone-aware
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        
        slots: List[Slot] = []

        # Normalize session type and determine online mode
        norm_in = self.normalize_session_type(session_type)
        is_online_session = norm_in == "online"
        now_utc = datetime.now(timezone.utc)

        # Collect busy intervals for this date once
        busy_intervals = self._day_busy_intervals(date)

        sel_loc = str(location or "").strip()
        for r in rules:
            if not isinstance(r, dict):
                continue
            matched = self._match_rule(date, r, sel_loc, norm_in)
            if not matched:
                continue
            window_start, window_end, duration_min, interval_min, r_loc_norm = matched

            for slot_start, slot_end in self.iter_free_slots(window_start, window_end, duration_min, interval_min, busy_intervals, now_utc):
                # Choose slot location
                if is_online_session:
                    slot_location: Optional[str] = None
                else:
                    slot_location = r_loc_norm if r_loc_norm not in ("any", "online") else (sel_loc or None)
                slot_id = f"{slot_start.isoformat()}|{(slot_location or 'online')}|{session_type}"
                slots.append(Slot(id=slot_id, start=slot_start, end=slot_end, location=slot_location, session_type=session_type))

        # Sort to ensure chronological order
        slots.sort(key=lambda s: s.start)
        return slots

    @staticmethod
    def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
        # Normalize to timezone-aware (UTC) to avoid naive/aware comparison errors
        if a_start.tzinfo is None:
            a_start = a_start.replace(tzinfo=timezone.utc)
        if a_end.tzinfo is None:
            a_end = a_end.replace(tzinfo=timezone.utc)
        if b_start.tzinfo is None:
            b_start = b_start.replace(tzinfo=timezone.utc)
        if b_end.tzinfo is None:
            b_end = b_end.replace(tzinfo=timezone.utc)
        return max(a_start, b_start) < min(a_end, b_end)

    def create_reservation(
        self,
        user_id: int,
        slot: Slot,
        name: str,
        phone: str | None,
        price: int = 100,
    ) -> Dict:
        # Ensure not double-booked: query only potentially conflicting bookings
        s_start = self.ensure_utc(slot.start)
        s_end = self.ensure_utc(slot.end)
        potentially_conflicting = self._bookings_repo.get_range_sync(s_start, s_end)
        for b in potentially_conflicting:
            try:
                bs = b.get("start")
                be = b.get("end")
                if not (isinstance(bs, str) and isinstance(be, str)):
                    continue
                b_start = datetime.fromisoformat(bs.replace("Z", "+00:00"))
                b_end = datetime.fromisoformat(be.replace("Z", "+00:00"))
            except Exception:
                continue
            if self.overlaps(s_start, s_end, b_start, b_end):
                raise ValidationError("Slot already booked")
        booking_id = f"b-{int(datetime.utcnow().timestamp())}-{user_id}"
        iso = lambda dt: dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        booking = {
            "id": booking_id,
            "user_id": str(user_id),
            "name": name,
            "phone": phone,
            "slot_id": slot.id,
            "start": iso(s_start),
            "end": iso(s_end),
            "location": slot.location,
            "session_type": slot.session_type,
            "status": "pending_payment",
            "price": price,
            "created_at": iso(datetime.utcnow().replace(tzinfo=timezone.utc)),
        }
        # Persist to Firestore
        self._bookings_repo.set_sync(booking)
        return booking

    def confirm_payment(self, booking_id: str) -> Dict:
        # Directly patch in Firestore and return the updated doc
        updated = self._bookings_repo.patch_sync(booking_id, {"status": "confirmed"})
        if not updated:
            raise KeyError("booking not found")
        return updated

    def list_user_bookings(self, user_id: int) -> List[Dict]:
        return self._bookings_repo.get_by_user_sync(user_id)

    def list_all_bookings(self) -> List[Dict]:
        return self._bookings_repo.get_all_sync()

    def cancel_booking(self, booking_id: str) -> Dict:
        # Load the booking by id to check cancelation constraints
        b = self._bookings_repo.get_by_id_sync(booking_id)
        if not b:
            raise KeyError("booking not found")
        s_s = b.get("start")
        if not isinstance(s_s, str) or not s_s:
            raise KeyError("booking not found")
        start = datetime.fromisoformat(s_s.replace("Z", "+00:00")).astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if start - now < timedelta(hours=24):
            # Cannot cancel: 24h rule
            raise PermissionError("Cannot cancel less than 24 hours")
        # Remove from Firestore
        self._bookings_repo.delete_sync(booking_id)
        canceled_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return {"id": booking_id, "status": "canceled", "canceled_at": canceled_at}

    def admin_delete_booking(self, booking_id: str) -> Dict:
        """Force-delete a booking regardless of time left (admin action)."""
        b = self._bookings_repo.get_by_id_sync(booking_id)
        if not b:
            raise KeyError("booking not found")
        # Delete from Firestore
        self._bookings_repo.delete_sync(booking_id)
        deleted_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return {"id": booking_id, "status": "deleted", "deleted_at": deleted_at}
