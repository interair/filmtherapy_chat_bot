import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.services.calendar_service import CalendarService, Slot
from src.exceptions import ValidationError


# ---------------------- Fake repositories ----------------------
class FakeBookingsRepo:
    def __init__(self):
        # store by id -> dict
        self.store: dict[str, dict] = {}

    # Helpers
    @staticmethod
    def _iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def add_booking(self, *, id: str, user_id: int | str, start: datetime, end: datetime, location: str | None, session_type: str, status: str = "confirmed", price: int = 100, name: str = "", phone: str | None = None):
        b = {
            "id": id,
            "user_id": str(user_id),
            "name": name,
            "phone": phone,
            "slot_id": f"{self._iso(start)}|{(location or 'online')}|{session_type}",
            "start": self._iso(start),
            "end": self._iso(end),
            "location": location,
            "session_type": session_type,
            "status": status,
            "price": price,
            "created_at": self._iso(datetime.now(timezone.utc)),
        }
        self.store[id] = b
        return b

    # Methods used by CalendarService
    def get_for_date_sync(self, date: datetime) -> list[dict]:
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        start_of_day = date.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        items: list[dict] = []
        for b in self.store.values():
            try:
                s = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            except Exception:
                continue
            if start_of_day <= s < end_of_day:
                items.append(dict(b))
        # mimic order by start
        items.sort(key=lambda x: x["start"])
        return items

    def get_range_sync(self, start: datetime, end: datetime) -> list[dict]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        items: list[dict] = []
        for b in self.store.values():
            try:
                s = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
            except Exception:
                continue
            if start <= s < end:
                items.append(dict(b))
        items.sort(key=lambda x: x["start"])
        return items

    def set_sync(self, booking: dict) -> dict:
        self.store[str(booking["id"])] = dict(booking)
        return booking

    def patch_sync(self, id: str, fields: dict) -> dict | None:
        cur = self.store.get(str(id))
        if not cur:
            return None
        cur.update(fields or {})
        self.store[str(id)] = cur
        return dict(cur)

    def get_by_user_sync(self, user_id: int | str) -> list[dict]:
        uid = str(user_id)
        out = [dict(b) for b in self.store.values() if str(b.get("user_id")) == uid]
        out.sort(key=lambda x: x.get("start", ""))
        return out

    def get_all_sync(self) -> list[dict]:
        return [dict(b) for b in self.store.values()]

    def get_by_id_sync(self, id: str) -> dict | None:
        b = self.store.get(str(id))
        return dict(b) if b else None

    def delete_sync(self, id: str) -> bool:
        return self.store.pop(str(id), None) is not None


class FakeScheduleRepo:
    def __init__(self, rules: list[dict] | None = None):
        self.rules = rules or []

    def get_sync(self):
        # CalendarService now expects a typed list of ScheduleRule
        from src.services.models import ScheduleRule
        out: list[ScheduleRule] = []
        for it in self.rules:
            out.append(ScheduleRule.model_validate(it))
        return out


# ---------------------- Fixtures ----------------------
@pytest.fixture()
def repos():
    bookings = FakeBookingsRepo()
    schedule = FakeScheduleRepo()
    return SimpleNamespace(bookings=bookings, schedule=schedule)


@pytest.fixture()
def service(repos) -> CalendarService:
    return CalendarService(repos.bookings, repos.schedule)


# ---------------------- Helper method tests ----------------------
def test_parse_hhmm_and_normalize_and_overlaps():
    # parse_hhmm
    assert CalendarService.parse_hhmm("10:30") == (10, 30)
    assert CalendarService.parse_hhmm("9") == (9, 0)
    assert CalendarService.parse_hhmm("24:00") is None
    assert CalendarService.parse_hhmm("oops") is None

    # normalize_session_type
    ns = CalendarService.normalize_session_type
    assert ns("") == "offline"
    assert ns("Онлайн") == "online"
    assert ns("any") == "any"
    assert ns("Песочная терапия") == "sand"
    assert ns("Очно") == "offline"
    assert ns("rest") == "rest"

    # normalize_location_rule
    nl = CalendarService.normalize_location_rule
    assert nl("") == "any"
    assert nl("любой") == "any"
    assert nl("Онлайн") == "online"
    assert nl("IJsbaanpad 9") == "IJsbaanpad 9"

    # ensure_utc
    naive = datetime(2050, 1, 1, 10, 0, 0)
    aware = naive.replace(tzinfo=timezone.utc)
    out1 = CalendarService.ensure_utc(naive)
    out2 = CalendarService.ensure_utc(aware)
    assert out1.tzinfo is timezone.utc
    assert out2 is aware

    # overlaps
    a0 = datetime(2050, 1, 1, 10, 0, tzinfo=timezone.utc)
    a1 = datetime(2050, 1, 1, 11, 0, tzinfo=timezone.utc)
    b0 = datetime(2050, 1, 1, 11, 0, tzinfo=timezone.utc)
    b1 = datetime(2050, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert not CalendarService.overlaps(a0, a1, b0, b1)  # touching at boundary is not overlap
    assert CalendarService.overlaps(a0, a1, a0, a1)


# ---------------------- list_available_slots tests ----------------------
def test_list_available_slots_offline_specific_location(service: CalendarService, repos):
    # Rule for 01-01-50, 10:00-12:00, 60-min slots at exact location
    date = datetime(2050, 1, 1, tzinfo=timezone.utc)
    rule = {"date": "01-01-50", "start": "10:00", "end": "12:00", "duration": 60, "interval": 60, "location": "IJsbaanpad 9", "session_type": "Очно"}
    repos.schedule.rules = [rule]

    slots = service.list_available_slots(date, location="IJsbaanpad 9", session_type="Очно")

    assert len(slots) == 2
    assert [s.start.hour for s in slots] == [10, 11]
    assert all(s.location == "IJsbaanpad 9" for s in slots)
    # Ensure sorted
    assert slots[0].start < slots[1].start


def test_list_available_slots_any_location_uses_selected(service: CalendarService, repos):
    date = datetime(2050, 1, 1, tzinfo=timezone.utc)
    rule = {"date": "01-01-50", "start": "10:00", "end": "12:00", "duration": 60, "interval": 60, "location": "any", "session_type": "Очно"}
    repos.schedule.rules = [rule]

    slots = service.list_available_slots(date, location="Van Eeghenlaan 27", session_type="Очно")
    assert len(slots) == 2
    assert all(s.location == "Van Eeghenlaan 27" for s in slots)


def test_list_available_slots_online_only_rule(service: CalendarService, repos):
    date = datetime(2050, 1, 1, tzinfo=timezone.utc)
    rule = {"date": "01-01-50", "start": "09:00", "end": "10:00", "duration": 30, "interval": 30, "location": "Онлайн", "session_type": "Онлайн"}
    repos.schedule.rules = [rule]

    # Online selection matches
    online_slots = service.list_available_slots(date, location=None, session_type="Онлайн")
    assert len(online_slots) == 2
    assert all(s.location is None for s in online_slots)

    # Offline selection should not match this rule
    offline_slots = service.list_available_slots(date, location="IJsbaanpad 9", session_type="Очно")
    assert offline_slots == []


def test_list_available_slots_excludes_busy_intervals(service: CalendarService, repos):
    date = datetime(2050, 1, 1, tzinfo=timezone.utc)
    rule = {"date": "01-01-50", "start": "10:00", "end": "12:00", "duration": 60, "interval": 60, "location": "IJsbaanpad 9", "session_type": "Очно"}
    repos.schedule.rules = [rule]

    # Pre-existing booking occupying 10:00-11:00 should remove the first slot
    start_busy = datetime(2050, 1, 1, 10, 0, tzinfo=timezone.utc)
    end_busy = datetime(2050, 1, 1, 11, 0, tzinfo=timezone.utc)
    repos.bookings.add_booking(id="b1", user_id=1, start=start_busy, end=end_busy, location="IJsbaanpad 9", session_type="Очно")

    slots = service.list_available_slots(date, location="IJsbaanpad 9", session_type="Очно")
    assert len(slots) == 1
    assert slots[0].start.hour == 11


# ---------------------- Booking operations tests ----------------------

def make_slot(start: datetime, end: datetime, location: str | None, session_type: str) -> Slot:
    slot_id = f"{start.isoformat()}|{(location or 'online')}|{session_type}"
    return Slot(id=slot_id, start=start, end=end, location=location, session_type=session_type)


def test_create_reservation_success_and_persist(service: CalendarService, repos):
    start = datetime(2050, 1, 2, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=60)
    slot = make_slot(start, end, location="IJsbaanpad 9", session_type="Очно")

    booking = service.create_reservation(user_id=42, slot=slot, name="John", phone="123")

    assert booking["status"] == "pending_payment"
    assert booking["user_id"] == "42"
    assert booking["start"].endswith("Z")
    assert repos.bookings.get_by_id_sync(booking["id"]) is not None


def test_create_reservation_conflict_raises(service: CalendarService, repos):
    # Existing booking starting inside the desired slot window
    busy_start = datetime(2050, 1, 3, 10, 15, tzinfo=timezone.utc)
    busy_end = busy_start + timedelta(minutes=60)
    repos.bookings.add_booking(id="busy", user_id=1, start=busy_start, end=busy_end, location="IJsbaanpad 9", session_type="Очно")

    slot_start = datetime(2050, 1, 3, 10, 0, tzinfo=timezone.utc)
    slot_end = slot_start + timedelta(minutes=60)
    slot = make_slot(slot_start, slot_end, location="IJsbaanpad 9", session_type="Очно")

    with pytest.raises(ValidationError):
        service.create_reservation(user_id=2, slot=slot, name="A", phone=None)


def test_confirm_payment_updates_status_and_missing_id(service: CalendarService, repos):
    # Create booking first
    start = datetime(2050, 1, 4, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=60)
    slot = make_slot(start, end, location=None, session_type="Онлайн")
    created = service.create_reservation(user_id=7, slot=slot, name="N", phone=None)

    updated = service.confirm_payment(created["id"])
    assert updated["status"] == "confirmed"

    # Missing id should raise KeyError per service contract
    with pytest.raises(KeyError):
        service.confirm_payment("nope")


def test_list_user_and_all_bookings(service: CalendarService, repos):
    # Seed two users
    base = datetime(2050, 1, 5, tzinfo=timezone.utc)
    repos.bookings.add_booking(id="b1", user_id=1, start=base, end=base + timedelta(minutes=50), location="IJsbaanpad 9", session_type="Очно")
    repos.bookings.add_booking(id="b2", user_id=2, start=base + timedelta(hours=1), end=base + timedelta(hours=2), location=None, session_type="Онлайн")

    u1 = service.list_user_bookings(1)
    assert len(u1) == 1 and u1[0]["id"] == "b1"

    all_b = service.list_all_bookings()
    ids = {b["id"] for b in all_b}
    assert {"b1", "b2"} <= ids


def test_cancel_booking_rules_and_admin_delete(service: CalendarService, repos):
    now = datetime.now(timezone.utc)

    # Far in the future: cancel should succeed
    far_start = now + timedelta(days=3)
    repos.bookings.add_booking(id="c1", user_id=1, start=far_start, end=far_start + timedelta(minutes=50), location=None, session_type="Онлайн")
    out = service.cancel_booking("c1")
    assert out["id"] == "c1" and out["status"] == "canceled"
    assert repos.bookings.get_by_id_sync("c1") is None

    # Less than 24h: should raise PermissionError
    soon_start = now + timedelta(hours=1)
    repos.bookings.add_booking(id="c2", user_id=1, start=soon_start, end=soon_start + timedelta(minutes=50), location="IJsbaanpad 9", session_type="Очно")
    with pytest.raises(PermissionError):
        service.cancel_booking("c2")

    # Missing id: KeyError
    with pytest.raises(KeyError):
        service.cancel_booking("missing")

    # Admin delete ignores 24h rule
    repos.bookings.add_booking(id="adm", user_id=1, start=soon_start, end=soon_start + timedelta(minutes=50), location="IJsbaanpad 9", session_type="Очно")
    out2 = service.admin_delete_booking("adm")
    assert out2["id"] == "adm" and out2["status"] == "deleted"
    assert repos.bookings.get_by_id_sync("adm") is None
