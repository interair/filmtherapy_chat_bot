from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from ..services.calendar_service import Slot


def _next_dates(n: int = 30) -> list[str]:  # Increased from 7 to 30 days
    """Return next n dates in ISO format (YYYY-MM-DD) for internal use."""
    today = datetime.utcnow().date()
    return [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


@dataclass
class BookingData:
    session_type: Optional[str] = None
    location: Optional[str] = None
    date: Optional[str] = None  # dd-mm-yy (user-facing)
    time: Optional[datetime] = None


class BookingFlow:
    def __init__(self, calendar_service, location_repo):
        self.calendar = calendar_service
        self.location_repo = location_repo
        # Add simple caching for the schedule
        self._schedule_cache = None
        self._schedule_cache_time = None

    async def create_booking(
        self,
        user_id: int,
        user_name: str,
        booking_data: BookingData,
        time_slot: datetime,
    ) -> dict:
        """Create a pending booking for the selected time slot.
        Minimal wrapper over CalendarService.create_reservation.
        """
        # Ensure timezone-aware
        if time_slot.tzinfo is None:
            time_slot = time_slot.replace(tzinfo=timezone.utc)
        # Build slot id deterministically to help deduplication/debugging
        slot = Slot(
            id=f"{time_slot.isoformat()}|{(booking_data.location or 'online')}|{booking_data.session_type}",
            start=time_slot,
            end=time_slot + timedelta(minutes=50),
            location=booking_data.location,
            session_type=booking_data.session_type or "Session",
        )
        # Create reservation via calendar service (may raise ValidationError)
        booking = self.calendar.create_reservation(
            user_id=user_id,
            slot=slot,
            name=user_name,
            phone=None,
        )
        return booking

    async def get_available_dates(self, session_type: str, location: Optional[str]) -> list[str]:
        """Fetch available dates within next 30 days.
        Returns dates formatted as dd-mm-yy for user display, while using ISO dates internally.
        """
        iso_dates = _next_dates(30)
        if not iso_dates:
            return []
        
        # Compute date range for a single query
        start_date = datetime.strptime(iso_dates[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(iso_dates[-1], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        
        # Fetch all bookings for the period in a single query
        all_bookings = self.calendar._bookings_repo.get_range_sync(start_date, end_date)
        
        # Group bookings by date (ISO keys)
        bookings_by_date = {}
        for booking in all_bookings:
            try:
                start_str = booking.get("start")
                if isinstance(start_str, str):
                    booking_date = datetime.fromisoformat(start_str.replace("Z", "+00:00")).date()
                    date_key = booking_date.strftime("%Y-%m-%d")
                    if date_key not in bookings_by_date:
                        bookings_by_date[date_key] = []
                    bookings_by_date[date_key].append(booking)
            except Exception:
                continue
        
        # Get schedule rules (with caching)
        schedule_rules = await self._get_schedule_rules()
        
        # Check each date for available slots
        out_dates: list[str] = []
        for iso in iso_dates:
            dt = datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if self._has_available_slots_optimized(
                dt, location, session_type, schedule_rules, bookings_by_date.get(iso, [])
            ):
                out_dates.append(dt.strftime("%d-%m-%y"))
        
        return out_dates

    async def _get_schedule_rules(self):
        """Cache schedule rules briefly to reduce Firestore reads (5 seconds TTL)."""
        now = datetime.utcnow()
        if (self._schedule_cache is None or 
            self._schedule_cache_time is None or 
            (now - self._schedule_cache_time).total_seconds() > 5):  # 5 seconds cache
            
            rules_models = self.calendar._schedule_repo.get_sync()
            self._schedule_cache = [r.model_dump(mode="python", exclude={"id"}) for r in (rules_models or [])]
            self._schedule_cache_time = now
        
        return self._schedule_cache

    def _has_available_slots_optimized(self, date: datetime, location: Optional[str], 
                                     session_type: str, schedule_rules: list, bookings: list) -> bool:
        """Fast check for availability without building the full list, reusing CalendarService helpers."""
        norm_in = self.calendar.normalize_session_type(session_type)
        now_utc = datetime.now(timezone.utc)

        # Convert bookings into busy intervals for this date
        busy_intervals = []
        for booking in bookings:
            try:
                s_s = booking.get("start")
                e_s = booking.get("end")
                if isinstance(s_s, str) and isinstance(e_s, str):
                    s_dt = self.calendar.ensure_utc(datetime.fromisoformat(s_s.replace("Z", "+00:00")))
                    e_dt = self.calendar.ensure_utc(datetime.fromisoformat(e_s.replace("Z", "+00:00")))
                    busy_intervals.append((s_dt, e_dt))
            except Exception:
                continue

        sel_loc = str(location or "").strip()
        for rule in schedule_rules:
            if not isinstance(rule, dict):
                continue
            matched = self.calendar._match_rule(date, rule, sel_loc, norm_in)
            if not matched:
                continue
            window_start, window_end, duration_min, interval_min, _ = matched

            # If at least one free slot exists, we're done
            for _slot in self.calendar.iter_free_slots(window_start, window_end, duration_min, interval_min, busy_intervals, now_utc):
                return True

        return False  # No free slots found

    async def get_available_times(self, date_str: str, session_type: str, location: Optional[str]) -> List[Slot]:
        """Return available time slots for a specific date.
        Expects date_str in dd-mm-yy format from the user interface.
        """
        date = datetime.strptime(date_str, "%d-%m-%y").replace(tzinfo=timezone.utc)
        return self.calendar.list_available_slots(date=date, location=location, session_type=session_type)
