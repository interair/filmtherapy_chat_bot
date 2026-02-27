from __future__ import annotations

import json as _json
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from typing import Generic, TypeVar, List, Optional, Dict, Any, Type

from pydantic import BaseModel, ValidationError as PydanticValidationError

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

from ..exceptions import NotFoundError, ValidationError

from .models import Event, Booking, Location, ScheduleRule
from .storage import (
    DATA_DIR,
    QUIZ_PATH,
    read_json,
)
from .firestore_client import get_async_client
from google.cloud.firestore_v1.base_query import FieldFilter

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

# Fast model validation cache for identical data payloads

def _dumps_sorted_bytes(obj: Any) -> bytes:
    if _orjson:
        return _orjson.dumps(obj, option=_orjson.OPT_SORT_KEYS)
    # Compact and sorted for stable hashing
    return _json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=4096)
def _validate_cached(model_cls: Type[T], payload: bytes) -> T:
    return model_cls.model_validate_json(payload)


def _normalize_iso_datetime(val: Any) -> str:
    """Normalize datetime values to ISO-8601 format with 'Z' suffix for UTC.
    
    Handles both datetime objects and string representations.
    """
    if isinstance(val, datetime):
        dt = val.astimezone(timezone.utc).replace(microsecond=0)
        return dt.isoformat().replace("+00:00", "Z")
    # Normalize pre-existing strings: ensure 'T' separator and 'Z' for UTC
    s = str(val)
    if "T" not in s and " " in s:
        s = s.replace(" ", "T")
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _normalize_dict_datetimes(data: dict, *field_names: str) -> dict:
    """Normalize datetime fields in a dictionary to ISO-8601 format."""
    for field in field_names:
        value = data.get(field)
        if value is not None:
            data[field] = _normalize_iso_datetime(value)
    return data


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
        self._db = get_async_client()
        self._col = self._db.collection(collection_name)
        self.model_class = model_class
        # Add validation cache per repository instance
        self._validation_cache = {}

    async def get_all(self) -> List[T]:
        items: List[T] = []
        # Use stream() which is an async generator in AsyncClient
        async for doc in self._col.stream():
            data = doc.to_dict() or {}
            if "id" not in data:
                data["id"] = doc.id
            try:
                payload = _dumps_sorted_bytes(data)
                items.append(_validate_cached(self.model_class, payload))
            except (PydanticValidationError, ValueError, TypeError) as e:
                logger.warning("Failed to validate document id=%s in collection: %s", doc.id, e, exc_info=True)
                continue
        return items

    async def get_by_id(self, item_id: str) -> Optional[T]:
        # Single document lookup - already optimized
        snap = await self._col.document(str(item_id)).get()
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
        snap = await ref.get()
        if snap.exists:
            raise ValidationError(f"Item with id '{doc_id}' already exists")
        # Use Python-native types (datetime) so Firestore stores Timestamps, not strings
        await ref.set(obj.model_dump(mode="python"))
        return obj

    async def update(self, item: T) -> T:
        obj = self.model_class.model_validate(item)
        if not hasattr(obj, "id") or not getattr(obj, "id"):
            raise ValidationError("Item must have 'id' field for updates")
        doc_id = str(getattr(obj, "id"))
        ref = self._col.document(doc_id)
        # Cache existence check result to avoid double reads
        snap = await ref.get()
        if not snap.exists:
            raise NotFoundError(f"Item with id '{doc_id}' not found")
        # Use Python-native types (datetime) so Firestore stores Timestamps, not strings
        await ref.set(obj.model_dump(mode="python"), merge=False)
        return obj

    async def delete(self, item_id: str) -> bool:
        ref = self._col.document(str(item_id))
        # Cache existence check result
        snap = await ref.get()
        if not snap.exists:
            return False
        await ref.delete()
        return True



class EventRepository(Repository[Event]):
    def __init__(self) -> None:
        self._repo = FirestoreRepository("events", Event)
        self._col = get_async_client().collection("events")
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
        async for doc in query.stream():
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            try:
                payload = _dumps_sorted_bytes(data)
                items.append(_validate_cached(Event, payload))
            except Exception as e:
                logger.warning("Failed to validate event from cached payload, doc_id=%s: %s", doc.id, e)
                try:
                    items.append(Event.model_validate(data))
                except Exception as e2:
                    logger.error("Failed to validate event doc_id=%s: %s", doc.id, e2, exc_info=True)
                    continue
        return items


class LocationRepository(Repository[Location]):
    """Firestore-backed repository for locations. Uses Location.name as doc id."""

    def __init__(self) -> None:
        self._repo = FirestoreRepository("locations", Location)
        self._col = get_async_client().collection("locations")

    async def get_all(self) -> List[Location]:
        return await self._repo.get_all()

    async def get_by_id(self, id: str) -> Optional[Location]:
        # Location names are doc IDs
        snap = await self._col.document(str(id).strip()).get()
        if not snap.exists:
            return None
        return Location(name=snap.id)

    async def create(self, item: Location) -> Location:
        loc = Location.model_validate(item)
        doc_id = str(loc.name).strip()
        ref = self._col.document(doc_id)
        snap = await ref.get()
        if snap.exists:
            raise ValidationError(f"Location '{loc.name}' already exists")
        await ref.set({"name": doc_id})
        return loc

    async def update(self, item: Location) -> Location:
        loc = Location.model_validate(item)
        doc_id = str(loc.name).strip()
        ref = self._col.document(doc_id)
        snap = await ref.get()
        if not snap.exists:
            raise NotFoundError(f"Location '{loc.name}' not found")
        # only normalization; keep doc with same id
        await ref.set({"name": doc_id}, merge=True)
        return loc

    async def delete(self, id: str) -> bool:
        ref = self._col.document(str(id).strip())
        snap = await ref.get()
        if not snap.exists:
            return False
        await ref.delete()
        return True

    async def exists(self, name: str) -> bool:
        snap = await self._col.document(str(name).strip()).get()
        return snap.exists


class QuizRepository:
    def __init__(self) -> None:
        self._doc = get_async_client().collection("config").document("quiz")

    async def get_config(self) -> Dict[str, Any]:
        snap = await self._doc.get()
        data = snap.to_dict() if snap.exists else None
        # Defaults: when Firestore is empty, load from local resource file and persist
        if not isinstance(data, dict) or not data:
            file_defaults = read_json(QUIZ_PATH, default={})
            data = file_defaults if isinstance(file_defaults, dict) else {}
            await self._doc.set(data)
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
            except Exception as e:
                logger.warning("Failed to parse mood item %s: %s", it, e)
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
            except Exception as e:
                logger.warning("Failed to parse company item %s: %s", it, e)
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
        await self._doc.set({"moods": out_moods, "companies": out_companies, "recs": out_recs}, merge=False)


class UserLanguageRepository:
    # Increase cache size for better hit rate
    _cache: Dict[str, Optional[str]] = {}
    _cache_timestamps: Dict[str, float] = {}
    _cache_ttl = 300  # 5 minutes TTL

    def __init__(self) -> None:
        self._col = get_async_client().collection("user_lang")

    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[key] < self._cache_ttl

    def _update_cache(self, key: str, value: Optional[str]) -> None:
        """Update cache with the given key and value."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    async def _fetch_language(self, user_id: int) -> Optional[str]:
        """Fetch language from Firestore for the given user_id."""
        key = str(user_id)
        snap = await self._col.document(key).get()
        
        if not snap.exists:
            self._update_cache(key, None)
            return None
        
        data = snap.to_dict() or {}
        val = data.get("lang")
        result = val if isinstance(val, str) and val else None
        self._update_cache(key, result)
        return result

    async def get(self, user_id: int) -> Optional[str]:
        key = str(user_id)
        if key in self._cache and self._is_cache_valid(key):
            return self._cache[key]
        return await self._fetch_language(user_id)

    async def set(self, user_id: int, lang: str) -> None:
        key = str(user_id)
        self._update_cache(key, str(lang))
        # Use merge=True to avoid overwriting other potential fields
        await self._col.document(key).set({"lang": str(lang)}, merge=True)


class AboutRepository:
    def __init__(self) -> None:
        self._doc = get_async_client().collection("config").document("about")

    async def _get_document_data(self) -> Dict[str, Any]:
        """Fetch and return document data from Firestore."""
        snap = await self._doc.get()
        return snap.to_dict() or {}

    async def get(self) -> Dict[str, Any]:
        return await self._get_document_data()

    async def save(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            data = {}
        # Do not store actual files in Firestore, only metadata (e.g., filename)
        await self._doc.set(data, merge=False)

    async def get_photo_file_path(self) -> Optional[str]:
        data = await self._get_document_data()
        fn = data.get("photo") if isinstance(data, dict) else None
        if not isinstance(fn, str) or not fn:
            return None
        path = os.path.join(DATA_DIR, fn)
        return path if os.path.exists(path) else None

    async def set_photo(self, filename: str) -> None:
        # Store only the filename in Firestore
        await self._doc.set({"photo": filename}, merge=True)

    # --- Film club (cinema) About photos management ---
    async def list_cinema_photos(self) -> list[str]:
        """Return list of saved cinema (film club) photo filenames that exist on disk."""
        data = await self._get_document_data()
        items = data.get("cinema_photos")
        if not isinstance(items, list):
            return []
        out: list[str] = []
        for it in items:
            if not isinstance(it, str) or not it:
                continue
            path = os.path.join(DATA_DIR, it)
            if os.path.exists(path):
                out.append(it)
        return out

    async def add_cinema_photo(self, filename: str) -> None:
        data = await self._get_document_data()
        items = data.get("cinema_photos")
        if not isinstance(items, list):
            items = []
        if filename not in items:
            items.append(filename)
        await self._doc.set({"cinema_photos": items}, merge=True)

    async def delete_cinema_photo(self, filename: str) -> None:
        data = await self._get_document_data()
        items = data.get("cinema_photos")
        if not isinstance(items, list):
            items = []
        items = [x for x in items if x != filename]
        await self._doc.set({"cinema_photos": items}, merge=True)


class ScheduleRepository:
    def __init__(self) -> None:
        # Use dedicated Firestore collection for schedule rules
        self._col = get_async_client().collection("schedule")

    # ---- Typed helpers ----------------------------------------------------
    @staticmethod
    def _normalize_rules(rules_in: List[ScheduleRule]) -> List[ScheduleRule]:
        """Normalize incoming ScheduleRule items into typed ScheduleRule models; invalid items are skipped."""
        out: List[ScheduleRule] = []
        for it in (rules_in or []):
            try:
                out.append(ScheduleRule.model_validate(it))
            except Exception as e:
                logger.warning("Failed to validate ScheduleRule item %s: %s", it, e, exc_info=True)
                continue
        return out

    @staticmethod
    def _doc_id_from_rule(rule: ScheduleRule) -> str:
        """Build a deterministic document id to enforce uniqueness on
        (date, location, session_type, start).
        """
        return str(rule.id or f"{rule.date}|{rule.start}|{rule.location or ''}|{rule.session_type or ''}")

    async def _fetch_rules(self) -> List[ScheduleRule]:
        """Fetch all schedule rules from Firestore."""
        items: List[ScheduleRule] = []
        async for doc in self._col.stream():
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            try:
                payload = _dumps_sorted_bytes(data)
                items.append(_validate_cached(ScheduleRule, payload))
            except Exception as e:
                logger.warning("Failed to validate ScheduleRule from cached payload, doc_id=%s: %s", doc.id, e)
                try:
                    items.append(ScheduleRule.model_validate(data))
                except Exception as e2:
                    logger.error("Failed to validate ScheduleRule doc_id=%s: %s", doc.id, e2, exc_info=True)
                    continue
        items.sort(key=lambda r: (r.date, r.start))
        return items

    async def _persist_rules(self, rules_in: List[ScheduleRule]) -> None:
        """Persist schedule rules to Firestore.
        New behavior: only explicitly delete rules that are marked with deleted=True.
        All other incoming rules are upserted. Existing rules not present in the payload are preserved.
        """
        new_rules = self._normalize_rules(rules_in)
        if not new_rules:
            return
        # Partition into deletes and upserts; last-wins deduplication by doc id
        to_delete_ids: set[str] = set()
        upserts: Dict[str, ScheduleRule] = {}
        for r in new_rules:
            doc_id = self._doc_id_from_rule(r)
            if getattr(r, "deleted", False):
                to_delete_ids.add(doc_id)
            else:
                upserts[doc_id] = r
        # Perform deletions by explicit ids
        for del_id in to_delete_ids:
            await self._col.document(del_id).delete()
        # Upsert new/updated rules (exclude id and deleted from stored doc)
        for doc_id, r in upserts.items():
            await self._col.document(doc_id).set(r.model_dump(mode="python", exclude={"id", "deleted"}), merge=False)

    async def get(self) -> List[ScheduleRule]:
        return await self._fetch_rules()

    async def save(self, rules_in: List[ScheduleRule]) -> None:
        await self._persist_rules(rules_in)

    # Optional typed API for future usage


class BookingRepository(Repository[Booking]):
    def __init__(self) -> None:
        self._repo = FirestoreRepository("bookings", Booking)
        self._col = get_async_client().collection("bookings")
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

    # --- Async helpers (previously sync) ---
    async def get_all_raw(self) -> List[dict]:
        items: List[dict] = []
        async for doc in self._col.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            # Ensure strings for datetime fields in ISO-8601 with Z
            _normalize_dict_datetimes(d, "start", "end", "created_at")
            items.append(d)
        return items

    async def get_by_id_raw(self, id: str) -> Optional[dict]:
        snap = await self._col.document(str(id)).get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        d.setdefault("id", snap.id)
        _normalize_dict_datetimes(d, "start", "end", "created_at")
        return d

    async def set_raw(self, booking: dict) -> dict:
        # Minimal validation: ensure id exists
        bid = str(booking.get("id") or "").strip()
        if not bid:
            raise ValidationError("Booking must have 'id'")
        await self._col.document(bid).set(booking, merge=False)
        return booking

    async def patch_raw(self, id: str, fields: dict) -> dict:
        snap = await self._col.document(str(id)).get()
        if not snap.exists:
            raise NotFoundError(f"Booking '{id}' not found")
        cur = snap.to_dict() or {}
        cur.update(fields or {})
        await self._col.document(str(id)).set(cur, merge=False)
        cur.setdefault("id", snap.id)
        return cur

    async def delete_raw(self, id: str) -> bool:
        ref = self._col.document(str(id))
        snap = await ref.get()
        if not snap.exists:
            return False
        await ref.delete()
        return True

    async def get_for_date(self, date: datetime) -> List[dict]:
        """Return bookings whose 'start' falls on the given date (UTC) using range query."""
        # Compute UTC day range
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        start_of_day = date.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        start_s = _normalize_iso_datetime(start_of_day)
        end_s = _normalize_iso_datetime(end_of_day)
        items: List[dict] = []
        
        # Optimized query with limit to prevent excessive data retrieval
        # Requires composite index on (start, ASC)
        query = (self._col
                .where(filter=FieldFilter("start", ">=", start_s))
                .where(filter=FieldFilter("start", "<", end_s))
                .order_by("start")
                .limit(50))  # Add reasonable limit
        
        async for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            _normalize_dict_datetimes(d, "start", "end", "created_at")
            items.append(d)
        return items

    async def get_range(self, start: datetime, end: datetime) -> List[dict]:
        """Return bookings with 'start' < end and 'start' >= start; further filtering can be applied by caller."""
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
            
        start_s = _normalize_iso_datetime(start)
        end_s = _normalize_iso_datetime(end)
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
        
        async for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            _normalize_dict_datetimes(d, "start", "end", "created_at")
            items.append(d)
        return items

    async def get_by_user(self, user_id: int | str) -> List[dict]:
        """Return bookings for the given user_id using equality filter."""
        uid = str(user_id)
        items: List[dict] = []
        
        # Optimized query with limit for user bookings
        # Requires composite index on (user_id, start, ASC) 
        query = (self._col
                .where(filter=FieldFilter("user_id", "==", uid))
                .order_by("start")
                .limit(100))  # Reasonable limit for user bookings
        
        async for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            _normalize_dict_datetimes(d, "start", "end", "created_at")
            items.append(d)
        return items



class EventRegistrationRepository:
    """Firestore-backed repository storing event registrations per (event_id, user_id).

    Document id format: "<event_id>:<user_id>". Stored fields: id, event_id, user_id, user_name, created_at.
    """
    def __init__(self) -> None:
        self._col = get_async_client().collection("event_regs")
        # Index hint: Single field index on event_id for get_by_event queries
        # Index hint: Single field index on user_id for list_by_user queries

    async def _fetch_by_field(self, field: str, value: int | str, order: bool = True, limit: int = 200) -> List[dict]:
        items: List[dict] = []
        val = str(value).strip()
        if not val:
            return items
        query = self._col.where(filter=FieldFilter(field, "==", val))
        if order:
            query = query.order_by("created_at")
        query = query.limit(limit)
        async for doc in query.stream():
            d = doc.to_dict() or {}
            d.setdefault("id", doc.id)
            items.append(d)
        return items

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
        await self._col.document(doc_id).set(data, merge=True)
        return data

    async def get_one(self, event_id: str, user_id: int | str) -> Optional[dict]:
        doc_id = self._doc_id(event_id, user_id)
        snap = await self._col.document(doc_id).get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        d.setdefault("id", snap.id)
        return d

    async def delete(self, event_id: str, user_id: int | str) -> bool:
        doc_id = self._doc_id(event_id, user_id)
        ref = self._col.document(doc_id)
        snap = await ref.get()
        if not snap.exists:
            return False
        await ref.delete()
        return True

    async def get_by_event(self, event_id: str) -> List[dict]:
        return await self._fetch_by_field("event_id", event_id, order=True, limit=200)

    async def list_by_user(self, user_id: int | str) -> List[dict]:
        """Return all event registrations for the specified user.
        Each item contains at least: id, event_id, user_id, user_name, created_at.
        """
        return await self._fetch_by_field("user_id", user_id, order=True, limit=200)


# SessionLocationsRepository: stores mapping of session types → list of locations
class SessionLocationsRepository:
    """Firestore-backed mapping of session type keys to lists of location names.

    Stored under collection 'config', document id 'session_locations'.
    Keys are arbitrary strings (e.g., 'Очно', 'Песочная терапия', 'Онлайн', 'cinema').
    Values are arrays of unique non-empty strings (location names).
    """

    def __init__(self) -> None:
        self._doc = get_async_client().collection("config").document("session_locations")

    async def get_map(self) -> Dict[str, List[str]]:
        snap = await self._doc.get()
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
        await self._doc.set(normalized, merge=False)

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
        return m.get(key, [])
