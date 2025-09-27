import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.services.event_service import EventService
from src.services.models import Event, EventCreate


@pytest.mark.asyncio
async def test_list_upcoming_events_returns_repo_results():
    # Arrange
    from datetime import datetime
    ev1 = Event(id="e1", title="T1", when=datetime.now(), place="P1")
    ev2 = Event(id="e2", title="T2", when=datetime.now(), place="P2", price=10.5)
    mock_repo = SimpleNamespace(
        get_upcoming=AsyncMock(return_value=[ev1, ev2])
    )
    service = EventService(mock_repo)

    # Act
    result = await service.list_upcoming_events()

    # Assert
    assert result == [ev1, ev2]
    mock_repo.get_upcoming.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_event_generates_id_and_calls_repo(monkeypatch):
    # Arrange
    from datetime import datetime

    class _FakeNow:
        def __init__(self, ts: int):
            self._ts = ts

        def timestamp(self) -> int:
            return self._ts

    class _FakeDatetime:
        @staticmethod
        def utcnow():
            return _FakeNow(1234567890)

    # Patch datetime used inside the service module
    import src.services.event_service as event_service_mod
    monkeypatch.setattr(event_service_mod, "datetime", _FakeDatetime)

    # Mock repo so that create returns the same event it receives
    mock_repo = SimpleNamespace(
        create=AsyncMock(side_effect=lambda ev: ev)
    )
    service = EventService(mock_repo)

    dto = EventCreate(
        title="My Event",
        when=datetime(2025, 1, 1, 12, 0, 0),
        place="Main Hall",
        price=99.9,
        description="Details",
    )

    # Act
    created = await service.create_event(dto)

    # Assert
    assert created.id == "event-1234567890"
    assert created.title == dto.title
    assert created.when == dto.when
    assert created.place == dto.place
    assert created.price == dto.price
    assert created.description == dto.description
    mock_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_event_forwards_to_repo():
    # Arrange
    mock_repo = SimpleNamespace(delete=AsyncMock(return_value=True))
    service = EventService(mock_repo)

    # Act
    ok = await service.delete_event("e42")

    # Assert
    assert ok is True
    mock_repo.delete.assert_awaited_once_with("e42")
