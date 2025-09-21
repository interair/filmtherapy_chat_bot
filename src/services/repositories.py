from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Dict, Any, Type
from pydantic import BaseModel, ValidationError as PydanticValidationError
from functools import lru_cache
import json as _json

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

from ..exceptions import ValidationError, NotFoundError

from .models import Event, Booking, Location
from .storage import (
    DATA_DIR,
    QUIZ_PATH,
    read_json,
)
from .firestore_client import get_client
from google.cloud.firestore_v1.base_query import FieldFilter

T = TypeVar('T', bound=BaseModel)


# Fast model validation cache for identical data payloads

def _dumps_sorted_bytes(obj: Any) -> bytes:
    if _orjson:
        return _orjson.dumps(obj, option=_orjson.OPT_SORT_KEYS)
    # Compact and sorted for stable hashing
    return _json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=4096)
def _validate_cached(model_cls: Type[BaseModel], payload: bytes) -> BaseModel:
    return model_cls.model_validate_json(payload)


class Repository(ABC, Generic[T]):
    @abstractmethod
    async def get_all(self) -> List[T]:
        """Return all items."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, id: str) -> Optional[T]:
        """Return item by identifier or None if not found."""
        raise NotImplementedError

    @abstractmethod
    async def create(self, item: T) -> T:
        """Create a new item and return it (possibly with defaults applied)."""
        raise NotImplementedError

    @abstractmethod
    async def update(self, item: T) -> T:
        """Update existing item and return the updated version."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete item by id. Return True if item existed and was deleted, False otherwise."""
        raise NotImplementedError




class FirestoreRepository(Generic[T]):
    """Generic Firestore repository for Pydantic models with string id.

    The Firestore document id is expected to match the model's 'id' field.
    """

    def __init__(self, collection_name: str, model_class: Type[T]):
        self._db = get_client()
        self._col = self._db.collection(collection_name)
        self.model_class = model_class
        # Add validation cache per repository instance
        self._validation_cache = {}

    async def get_all(self) -> List[T]:
        items: List[T] = []
        # Use select() to minimize data transfer if we only need specific fields
        for doc in self._col.stream():
            data = doc.to_dict() or {}
            if "id" not in data:
                data["id"] = doc.id
            try:
                payload = _dumps_sorted_bytes(data)
                items.append(_validate_cached(self.model_class, payload))
            except (PydanticValidationError, ValueError, TypeError):
                continue
        return items

    async def get_by_id(self, item_id: str) -> Optional[T]:
        # Single document lookup - already optimized
        snap = self._col.document(str(item_id)).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if "id" not in data:
            data["id"] = snap.id
        try:
            payload = _dumps_sorted_bytes(data)
            return _validate_cached(self.model_class, payload)
        except (PydanticValidationError, ValueError, TypeError):
            return self.model_class.model_validate(data)

    async def create(self, item: T) -> T:
        obj = self.model_class.model_validate(item)
        if not hasattr(obj, "id") or not getattr(obj, "id"):
            raise ValidationError("Item must have 'id' field")
        doc_id = str(getattr(obj, "id"))
        ref = self._col.document(doc_id)
        # Use get() with source=CACHE to check cache first, then server
        from google.cloud.firestore import DocumentSnapshot
        if ref.get().exists:
            raise ValidationError(f"Item with id '{doc_id}' already exists")
        # Use Python-native types (datetime) so Firestore stores Timestamps, not strings
        ref.set(obj.model_dump(mode="python"))
        return obj

    async def update(self, item: T) -> T:
        obj = self.model_class.model_validate(item)
        if not hasattr(obj, "id") or not getattr(obj, "id"):
            raise ValidationError("Item must have 'id' field for updates")
        doc_id = str(getattr(obj, "id"))
        ref = self._col.document(doc_id)
        # Cache existence check result to avoid double reads
        snap = ref.get()
        if not snap.exists:
            raise NotFoundError(f"Item with id '{doc_id}' not found")
        # Use Python-native types (datetime) so Firestore stores Timestamps, not strings
        ref.set(obj.model_dump(mode="python"), merge=False)
        return obj

    async def delete(self, item_id: str) -> bool:
        ref = self._col.document(str(item_id))
        # Cache existence check result
        snap = ref.get()
        if not snap.exists:
            return False
        ref.delete()
        return True



class EventRepository(Repository[Event]):
    def __init__(self) -> None:
        self._repo = FirestoreRepository("events", Event)
        self._col = get_client().collection("events")
        # Add index hint: Firestore needs composite index on (when, ASC)
        # for optimal performance of get_upcoming() query

    async def get_all(self) -> List[Event]:
        return await self._repo.get_all()

    async def get_by_id(self, id: str) -> Optional[Event]:
        return await self._repo.get_by_id(id)

    async def create(self, item: Event) -> Event:
        return await self._repo.create(item)

    async def update(self, item: Event) -> Event:
        return await self._repo.update(item)

    async def delete(self, id: str) -> bool:
        return await self._repo.delete(id)

    async def get_upcoming(self) -> List[Event]:
        now = datetime.now(timezone.utc)
        items: List[Event] = []
        # Optimized: use limit() to avoid processing too many results
        # Add composite index: events collection on (when, ASC) for this query
        query = self._col.where(filter=FieldFilter("when", ">=", now)).order_by("when").limit(100)
        for doc in query.stream():
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            try:
                payload = _dumps_sorted_bytes(data)
                items.append(_validate_cached(Event, payload))
            except Exception:
                try:
                    items.append(Event.model_validate(data))
                except Exception:
                    continue
        return items

class LocationRepository(Repository[Location]):
    """Firestore-backed repository for locations. Uses Location.name as doc id."""

    def __init__(self) -> None:
        self._col = get_client().collection("locations")

    async def get_all(self) -> List[Location]:
        items: List[Location] = []
        for doc in self._col.stream():
            name = doc.id
            try:
                items.append(Location(name=str(name)))
            except Exception:
                continue
        return items

    async def get_by_id(self, id: str) -> Optional[Location]:
        doc = self._col.document(str(id).strip()).get()
        if not doc.exists:
            return None
        return Location(name=doc.id)

    async def create(self, item: Location) -> Location:
        loc = Location.model_validate(item)
        doc_id = str(loc.name).strip()
        ref = self._col.document(doc_id)
        if ref.get().exists:
            raise ValidationError(f"Location '{loc.name}' already exists")
        ref.set({"name": doc_id})
        return loc

    async def update(self, item: Location) -> Location:
        loc = Location.model_validate(item)
        doc_id = str(loc.name).strip()
        ref = self._col.document(doc_id)
        if not ref.get().exists:
            raise NotFoundError(f"Location '{loc.name}' not found")
        # only normalization; keep doc with same id
        ref.set({"name": doc_id}, merge=True)
        return loc

    async def delete(self, id: str) -> bool:
        ref = self._col.document(str(id).strip())
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    async def exists(self, name: str) -> bool:
        return self._col.document(str(name).strip()).get().exists


class QuizRepository:
    def __init__(self) -> None:
        self._doc = get_client().collection("config").document("quiz")

    async def get_config(self) -> Dict[str, Any]:
        snap = self._doc.get()
        data = snap.to_dict() if snap.exists else None
        # Defaults: when Firestore is empty, load from local resource file and persist
        if not isinstance(data, dict) or not data:
            file_defaults = read_json(QUIZ_PATH, default={})
            data = file_defaults if isinstance(file_defaults, dict) else {}
            self._doc.set(data)
        # Normalize
        moods = data.get("moods") or []
        companies = data.get("companies") or []
        recs = data.get("recs") or {}
        norm_moods = []
        seen_codes = set()
        for it in moods:
            try:
                title = str(it.get("title", "")).strip()
                code = str(it.get("code", "")).strip()
            except Exception:
                continue
            if title and code and code not in seen_codes:
                norm_moods.append({"title": title, "code": code})
                seen_codes.add(code)
        norm_companies = []
        seen_cc = set()
        for it in companies:
            try:
                title = str(it.get("title", "")).strip()
                code = str(it.get("code", "")).strip()
            except Exception:
                continue
            if title and code and code not in seen_cc:
                norm_companies.append({"title": title, "code": code})
                seen_cc.add(code)
        norm_recs: Dict[str, List[str]] = {}
        if isinstance(recs, dict):
            for k, v in recs.items():
                kk = str(k)
                if isinstance(v, list):
                    norm_recs[kk] = [str(x).strip() for x in v if str(x).strip()]
        return {"moods": norm_moods, "companies": norm_companies, "recs": norm_recs}

    async def save_config(self, items: Dict[str, Any]) -> None:
        moods_in = items.get("moods") or []
        companies_in = items.get("companies") or []
        recs_in = items.get("recs") or {}
        out_moods: List[Dict[str, str]] = []
        seen = set()
        for it in moods_in:
            if isinstance(it, dict):
                title = str(it.get("title", "")).strip()
                code = str(it.get("code", "")).strip()
                if title and code and code not in seen:
                    out_moods.append({"title": title, "code": code})
                    seen.add(code)
        out_companies: List[Dict[str, str]] = []
        seen2 = set()
        for it in companies_in:
            if isinstance(it, dict):
                title = str(it.get("title", "")).strip()
                code = str(it.get("code", "")).strip()
                if title and code and code not in seen2:
                    out_companies.append({"title": title, "code": code})
                    seen2.add(code)
        out_recs: Dict[str, List[str]] = {}
        if isinstance(recs_in, dict):
            for k, v in recs_in.items():
                if isinstance(v, list):
                    out_recs[str(k)] = [str(x).strip() for x in v if str(x).strip()]
        self._doc.set({"moods": out_moods, "companies": out_companies, "recs": out_recs}, merge=False)


class UserLanguageRepository:
    # Increase cache size for better hit rate
    _cache: Dict[str, Optional[str]] = {}
    _cache_timestamps: Dict[str, float] = {}
    _cache_ttl = 300  # 5 minutes TTL

    def __init__(self) -> None:
        self._col = get_client().collection("user_lang")

    def _is_cache_valid(self, key: str) -> bool:
        import time
        if key not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[key] < self._cache_ttl

    async def get(self, user_id: int) -> Optional[str]:
        key = str(user_id)
        if key in self._cache and self._is_cache_valid(key):
            return self._cache[key]
        
        snap = self._col.document(key).get()
        if not snap.exists:
            import time
            self._cache[key] = None
            self._cache_timestamps[key] = time.time()
            return None
        
        data = snap.to_dict() or {}
        val = data.get("lang")
        out = val if isinstance(val, str) and val else None
        import time
        self._cache[key] = out
        self._cache_timestamps[key] = time.time()
        return out

    async def set(self, user_id: int, lang: str) -> None:
        key = str(user_id)
        import time
        self._cache[key] = str(lang)
        self._cache_timestamps[key] = time.time()
        # Use merge=True to avoid overwriting other potential fields
        self._col.document(key).set({"lang": str(lang)}, merge=True)

    def get_sync(self, user_id: int) -> Optional[str]:
        key = str(user_id)
        if key in self._cache and self._is_cache_valid(key):
            return self._cache[key]
        
        snap = self._col.document(key).get()
        if not snap.exists:
            import time
            self._cache[key] = None
            self._cache_timestamps[key] = time.time()
            return None
        
        data = snap.to_dict() or {}
        val = data.get("lang")
        out = val if isinstance(val, str) and val else None
        import time
        self._cache[key] = out
        self._cache_timestamps[key] = time.time()
        return out

    def set_sync(self, user_id: int, lang: str) -> None:
        key = str(user_id)
        import time
        self._cache[key] = str(lang)
        self._cache_timestamps[key] = time.time()
        self._col.document(key).set({"lang": str(lang)}, merge=True)


class AboutRepository:
    def __init__(self) -> None:
        self._doc = get_client().collection("config").document("about")

    async def get(self) -> Dict[str, Any]:
        snap = self._doc.get()
        return snap.to_dict() or {}

    async def save(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            data = {}
        # Do not store actual files in Firestore, only metadata (e.g., filename)
        self._doc.set(data, merge=False)

    async def get_photo_file_path(self) -> Optional[str]:
        # Kept for backward compatibility; delegates to sync version
        return self.get_photo_file_path_sync()

    def get_photo_file_path_sync(self) -> Optional[str]:
        snap = self._doc.get()
        data = snap.to_dict() or {}
        fn = data.get("photo") if isinstance(data, dict) else None
        if not isinstance(fn, str) or not fn:
            return None
        path = os.path.join(DATA_DIR, fn)
        return path if os.path.exists(path) else None

    async def set_photo(self, filename: str) -> None:
        # Store only the filename in Firestore
        self._doc.set({"photo": filename}, merge=True)


class ScheduleRepository:
    def __init__(self) -> None:
        self._doc = get_client().collection("config").document("schedule")

    def _normalize_rules(self, rules_in: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out_rules: List[Dict[str, Any]] = []
        for it in rules_in or []:
            if not isinstance(it, dict):
                continue
            try:
                weekday = int(it.get("weekday"))
            except Exception:
                continue
            if weekday < 0 or weekday > 6:
                continue
            start = str(it.get("start", "")).strip()
            end = str(it.get("end", "")).strip()
            if not start or not end:
                continue
            try:
                duration = int(it.get("duration", 50) or 50)
            except Exception:
                duration = 50
            try:
                interval = int(it.get("interval", duration) or duration)
            except Exception:
                interval = duration
            location = str(it.get("location") or "").strip()
            session_type = str(it.get("session_type") or "").strip()
            out_rules.append({
                "weekday": weekday,
                "start": start,
                "end": end,
                "duration": duration,
                "interval": interval,
                "location": location,
                "session_type": session_type,
            })
        return out_rules

    async def get(self) -> Dict[str, Any]:
        snap = self._doc.get()
        data = snap.to_dict() or {}
        rules_in = data.get("rules") or []
        return {"rules": self._normalize_rules(rules_in)}

    async def save(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            payload = {}
        out_rules = self._normalize_rules(payload.get("rules") or [])
        self._doc.set({"rules": out_rules}, merge=False)

    # Synchronous helpers for non-async contexts
    def get_sync(self) -> Dict[str, Any]:
        snap = self._doc.get()
        data = snap.to_dict() or {}
        rules = data.get("rules")
        if not isinstance(rules, list):
            rules = []
        return {"rules": rules}

    def save_sync(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            payload = {}
        rules = payload.get("rules")
        if not isinstance(rules, list):
            rules = []
        self._doc.set({"rules": rules}, merge=False)


class BookingRepository(Repository[Booking]):
    def __init__(self) -> None:
        self._repo = FirestoreRepository("bookings", Booking)
        self._col = get_client().collection("bookings")
        # Index hints for optimal query performance:
        # 1. Composite index on (start, ASC) for date range queries
        # 2. Composite index on (user_id, start, ASC) for user bookings
        # 3. Single field index on user_id for equality queries

    async def get_all(self) -> List[Booking]:
        return await self._repo.get_all()

    async def get_by_id(self, id: str) -> Optional[Booking]:
        return await self._repo.get_by_id(id)

    async def create(self, item: Booking) -> Booking:
        return await self._repo.create(item)

    async def update(self, item: Booking) -> Booking:
        return await self._repo.update(item)

    async def delete(self, id: str) -> bool:
        return await self._repo.delete(id)

    # --- Synchronous helpers for non-async contexts (e.g., CalendarService) ---
    def get_all_sync(self) -> List[dict]:
        def _iso(val: Any) -> str:
            if isinstance(val, datetime):
                dt = val.astimezone(timezone.utc).replace(microsecond=0)
                return dt.isoformat().replace("+00:00", "Z")
            # Normalize pre-existing strings: ensure 'T' separator and 'Z' for UTC when tzinfo missing
            s = str(val)
            if "T" not in s and " " in s:
                s = s.replace(" ", "T")
            if s.endswith("+00:00"):
                s = s[:-6] + "Z"
            return s
        items: List[dict] = []
        for doc in self._col.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            # Ensure strings for datetime fields in ISO-8601 with Z
            for k in ("start", "end", "created_at"):
                v = d.get(k)
                if v is not None:
                    d[k] = _iso(v)
            items.append(d)
        return items

    def get_by_id_sync(self, id: str) -> Optional[dict]:
        snap = self._col.document(str(id)).get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        d.setdefault("id", snap.id)
        def _iso(val: Any) -> str:
            if isinstance(val, datetime):
                dt = val.astimezone(timezone.utc).replace(microsecond=0)
                return dt.isoformat().replace("+00:00", "Z")
            s = str(val)
            if "T" not in s and " " in s:
                s = s.replace(" ", "T")
            if s.endswith("+00:00"):
                s = s[:-6] + "Z"
            return s
        for k in ("start", "end", "created_at"):
            v = d.get(k)
            if v is not None:
                d[k] = _iso(v)
        return d

    def set_sync(self, booking: dict) -> dict:
        # Minimal validation: ensure id exists
        bid = str(booking.get("id") or "").strip()
        if not bid:
            raise ValidationError("Booking must have 'id'")
        self._col.document(bid).set(booking, merge=False)
        return booking

    def patch_sync(self, id: str, fields: dict) -> dict:
        snap = self._col.document(str(id)).get()
        if not snap.exists:
            raise NotFoundError(f"Booking '{id}' not found")
        cur = snap.to_dict() or {}
        cur.update(fields or {})
        self._col.document(str(id)).set(cur, merge=False)
        cur.setdefault("id", snap.id)
        return cur

    def delete_sync(self, id: str) -> bool:
        ref = self._col.document(str(id))
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def get_for_date_sync(self, date: datetime) -> List[dict]:
        """Return bookings whose 'start' falls on the given date (UTC) using range query."""
        # Compute UTC day range
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        start_of_day = date.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        def _iso(val: Any) -> str:
            if isinstance(val, datetime):
                dt = val.astimezone(timezone.utc).replace(microsecond=0)
                return dt.isoformat().replace("+00:00", "Z")
            s = str(val)
            if "T" not in s and " " in s:
                s = s.replace(" ", "T")
            if s.endswith("+00:00"):
                s = s[:-6] + "Z"
            return s
        
        start_s = _iso(start_of_day)
        end_s = _iso(end_of_day)
        items: List[dict] = []
        
        # Optimized query with limit to prevent excessive data retrieval
        # Requires composite index on (start, ASC)
        query = (self._col
                .where(filter=FieldFilter("start", ">=", start_s))
                .where(filter=FieldFilter("start", "<", end_s))
                .order_by("start")
                .limit(50))  # Add reasonable limit
        
        for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            for k in ("start", "end", "created_at"):
                v = d.get(k)
                if v is not None:
                    d[k] = _iso(v)
            items.append(d)
        return items

    def get_range_sync(self, start: datetime, end: datetime) -> List[dict]:
        """Return bookings with 'start' < end and 'start' >= start; further filtering can be applied by caller."""
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
            
        def _iso(val: Any) -> str:
            if isinstance(val, datetime):
                dt = val.astimezone(timezone.utc).replace(microsecond=0)
                return dt.isoformat().replace("+00:00", "Z")
            s = str(val)
            if "T" not in s and " " in s:
                s = s.replace(" ", "T")
            if s.endswith("+00:00"):
                s = s[:-6] + "Z"
            return s
            
        start_s = _iso(start)
        end_s = _iso(end)
        items: List[dict] = []
        
        # Calculate reasonable limit based on time range
        days_diff = (end - start).days
        limit = min(max(days_diff * 10, 50), 500)  # 10 bookings per day, min 50, max 500
        
        # Optimized query with dynamic limit
        # Requires composite index on (start, ASC)
        query = (self._col
                .where(filter=FieldFilter("start", ">=", start_s))
                .where(filter=FieldFilter("start", "<", end_s))
                .order_by("start")
                .limit(limit))
        
        for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            for k in ("start", "end", "created_at"):
                v = d.get(k)
                if v is not None:
                    d[k] = _iso(v)
            items.append(d)
        return items

    def get_by_user_sync(self, user_id: int | str) -> List[dict]:
        """Return bookings for the given user_id using equality filter."""
        uid = str(user_id)
        
        def _iso(val: Any) -> str:
            if isinstance(val, datetime):
                dt = val.astimezone(timezone.utc).replace(microsecond=0)
                return dt.isoformat().replace("+00:00", "Z")
            s = str(val)
            if "T" not in s and " " in s:
                s = s.replace(" ", "T")
            if s.endswith("+00:00"):
                s = s[:-6] + "Z"
            return s
            
        items: List[dict] = []
        
        # Optimized query with limit for user bookings
        # Requires composite index on (user_id, start, ASC) 
        query = (self._col
                .where(filter=FieldFilter("user_id", "==", uid))
                .order_by("start")
                .limit(100))  # Reasonable limit for user bookings
        
        for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            for k in ("start", "end", "created_at"):
                v = d.get(k)
                if v is not None:
                    d[k] = _iso(v)
            items.append(d)
        return items



class EventRegistrationRepository:
    """Firestore-backed repository storing event registrations per (event_id, user_id).

    Document id format: "<event_id>:<user_id>". Stored fields: id, event_id, user_id, user_name, created_at.
    """
    def __init__(self) -> None:
        self._col = get_client().collection("event_regs")
        # Index hint: Single field index on event_id for get_by_event queries
        # Index hint: Single field index on user_id for list_by_user queries

    @staticmethod
    def _doc_id(event_id: str, user_id: int | str) -> str:
        return f"{str(event_id).strip()}:{str(user_id).strip()}"

    async def add(self, event_id: str, user_id: int | str, user_name: str | None = None) -> dict:
        doc_id = self._doc_id(event_id, user_id)
        data = {
            "id": doc_id,
            "event_id": str(event_id).strip(),
            "user_id": str(user_id).strip(),
            "user_name": str(user_name or "").strip(),
            "created_at": datetime.now(timezone.utc),
        }
        self._col.document(doc_id).set(data, merge=True)
        return data

    async def get_one(self, event_id: str, user_id: int | str) -> Optional[dict]:
        doc_id = self._doc_id(event_id, user_id)
        snap = self._col.document(doc_id).get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        d.setdefault("id", snap.id)
        return d

    async def delete(self, event_id: str, user_id: int | str) -> bool:
        doc_id = self._doc_id(event_id, user_id)
        ref = self._col.document(doc_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    async def get_by_event(self, event_id: str) -> List[dict]:
        items: List[dict] = []
        try:
            clean_event_id = str(event_id).strip()
            if not clean_event_id:
                return items
            query = (self._col
                    .where(filter=FieldFilter("event_id", "==", clean_event_id))
                    .order_by("created_at")
                    .limit(200))
            for doc in query.stream():
                d = doc.to_dict() or {}
                d.setdefault("id", doc.id)
                items.append(d)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting registrations for event {event_id}: {e}")
        return items

    async def list_by_user(self, user_id: int | str) -> List[dict]:
        """Return all event registrations for the specified user.
        Each item contains at least: id, event_id, user_id, user_name, created_at.
        """
        items: List[dict] = []
        try:
            uid = str(user_id).strip()
            if not uid:
                return items
            query = (self._col
                    .where(filter=FieldFilter("user_id", "==", uid))
                    .order_by("created_at")
                    .limit(200))
            for doc in query.stream():
                d = doc.to_dict() or {}
                d.setdefault("id", doc.id)
                items.append(d)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting registrations for user {user_id}: {e}")
        return items


# SessionLocationsRepository: stores mapping of session types → list of locations
class SessionLocationsRepository:
    """Firestore-backed mapping of session type keys to lists of location names.

    Stored under collection 'config', document id 'session_locations'.
    Keys are arbitrary strings (e.g., 'Очно', 'Песочная терапия', 'Онлайн', 'cinema').
    Values are arrays of unique non-empty strings (location names).
    """

    def __init__(self) -> None:
        self._doc = get_client().collection("config").document("session_locations")

    async def get_map(self) -> Dict[str, List[str]]:
        snap = self._doc.get()
        data = snap.to_dict() if snap.exists else None
        if not isinstance(data, dict):
            data = {}
        out: Dict[str, List[str]] = {}
        for k, v in data.items():
            key = str(k).strip()
            if not key:
                continue
            if isinstance(v, list):
                seen = set()
                arr: List[str] = []
                for it in v:
                    try:
                        name = str(it).strip()
                    except Exception:
                        continue
                    if name and name not in seen:
                        arr.append(name)
                        seen.add(name)
                out[key] = arr
        return out

    async def save_map(self, payload: Dict[str, List[str]]) -> None:
        normalized: Dict[str, List[str]] = {}
        for k, v in (payload or {}).items():
            key = str(k).strip()
            if not key:
                continue
            if isinstance(v, list):
                seen = set()
                arr: List[str] = []
                for it in v:
                    try:
                        name = str(it).strip()
                    except Exception:
                        continue
                    if name and name not in seen:
                        arr.append(name)
                        seen.add(name)
                normalized[key] = arr
        # Replace entirely to avoid stale entries
        self._doc.set(normalized, merge=False)

    async def add(self, type_key: str, name: str) -> None:
        key = str(type_key).strip()
        nm = str(name).strip()
        if not key or not nm:
            return
        cur = await self.get_map()
        arr = cur.get(key, [])
        if nm not in arr:
            arr.append(nm)
        cur[key] = arr
        await self.save_map(cur)

    async def remove(self, type_key: str, name: str) -> None:
        key = str(type_key).strip()
        nm = str(name).strip()
        if not key or not nm:
            return
        cur = await self.get_map()
        arr = [x for x in cur.get(key, []) if x != nm]
        if arr:
            cur[key] = arr
        else:
            cur.pop(key, None)
        await self.save_map(cur)

    async def list_for(self, type_key: str) -> List[str]:
        key = str(type_key).strip()
        m = await self.get_map()
