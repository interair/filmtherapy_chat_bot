import pytest
from types import SimpleNamespace

from src.services.repositories import ScheduleRepository
from src.services.models import ScheduleRule


class FakeSnap:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = dict(data)

    def to_dict(self):
        return dict(self._data)


class FakeDocRef:
    def __init__(self, store: dict, doc_id: str):
        self._store = store
        self.id = doc_id

    def set(self, data: dict, merge: bool = False):
        # Firestore set(merge=False) replaces the doc
        self._store[self.id] = dict(data)

    def delete(self):
        self._store.pop(self.id, None)


class FakeCollection:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def document(self, doc_id: str) -> FakeDocRef:
        return FakeDocRef(self._store, doc_id)

    def stream(self):
        # Return snapshot-like objects
        return [FakeSnap(doc_id, data) for doc_id, data in self._store.items()]


class FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


@pytest.fixture()
def fake_firestore(monkeypatch):
    fake = FakeFirestoreClient()
    # Patch the get_client used inside repositories module
    import src.services.repositories as repos_mod
    monkeypatch.setattr(repos_mod, "get_client", lambda: fake)
    return fake


def make_rule(date: str, start: str, end: str, duration: int = 50, interval: int | None = None, location: str = "", session_type: str = "") -> ScheduleRule:
    return ScheduleRule(
        date=date,
        start=start,
        end=end,
        duration=duration,
        interval=interval,
        location=location,
        session_type=session_type,
    )


@pytest.mark.asyncio
async def test_save_and_get_roundtrip_sorted(fake_firestore):
    repo = ScheduleRepository()

    r1 = make_rule("01-01-30", "10:00", "12:00", duration=60, interval=30, location="LocA", session_type="Онлайн")
    r2 = make_rule("01-01-30", "09:00", "11:00", duration=45, interval=15, location="LocB", session_type="")

    # Save two rules
    await repo.save([r1, r2])

    # Underlying store should have two docs with ids as in rules
    col = fake_firestore.collection("schedule")
    store_ids = set(col._store.keys())
    assert store_ids == {r1.id, r2.id}

    # Ensure payloads do not include id or deleted flag
    for doc_id, payload in col._store.items():
        assert "id" not in payload
        assert "deleted" not in payload
        assert isinstance(payload.get("date"), str)

    # Read back and verify sorting by (date, start)
    out = await repo.get()
    assert [x.id for x in out] == [r2.id, r1.id]


@pytest.mark.asyncio
async def test_save_deletes_only_when_explicit(fake_firestore):
    repo = ScheduleRepository()
    r1 = make_rule("02-01-30", "10:00", "12:00")
    r2 = make_rule("02-01-30", "13:00", "15:00")
    await repo.save([r1, r2])

    # Saving only a subset should NOT delete others anymore
    await repo.save([r2])
    col = fake_firestore.collection("schedule")
    assert set(col._store.keys()) == {r1.id, r2.id}

    # Now delete r1 explicitly using the deleted flag
    r1_deleted = make_rule("02-01-30", "10:00", "12:00")
    r1_deleted.deleted = True
    await repo.save([r1_deleted])
    assert set(col._store.keys()) == {r2.id}


@pytest.mark.asyncio
async def test_save_deduplicates_by_doc_id_last_wins(fake_firestore):
    repo = ScheduleRepository()
    # Same composite key (date|start|location|session_type), differ by end/duration
    a = make_rule("03-01-30", "10:00", "11:00", duration=30, location="Room1", session_type="Очно")
    b = make_rule("03-01-30", "10:00", "12:00", duration=60, location="Room1", session_type="Очно")
    assert a.id == b.id  # sanity: composite keys match

    await repo.save([a, b])

    col = fake_firestore.collection("schedule")
    assert set(col._store.keys()) == {a.id}
    # Last item should win
    expected = b.model_dump(mode="python", exclude={"id", "deleted"})
    assert col._store[a.id] == expected


@pytest.mark.asyncio
async def test_save_ignores_invalid_items(fake_firestore):
    repo = ScheduleRepository()
    valid = make_rule("04-01-30", "10:00", "11:00")
    # Include non-rule garbage; repository should ignore invalid items without raising
    await repo.save([valid, "oops", 123])  # type: ignore[list-item]

    col = fake_firestore.collection("schedule")
    assert set(col._store.keys()) == {valid.id}


def test_sync_methods_match_async(fake_firestore):
    repo = ScheduleRepository()
    r1 = make_rule("05-01-30", "08:00", "09:00")
    r2 = make_rule("05-01-30", "07:00", "08:00")

    # Use sync save
    repo.save_sync([r1, r2])

    # get_sync returns sorted
    out_sync = repo.get_sync()
    assert [x.id for x in out_sync] == [r2.id, r1.id]

    # And internal store contains the same ids
    col = fake_firestore.collection("schedule")
    assert set(col._store.keys()) == {r1.id, r2.id}
