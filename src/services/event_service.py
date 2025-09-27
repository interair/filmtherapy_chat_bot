from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from .models import Event, EventCreate
from .repositories import EventRepository

logger = logging.getLogger(__name__)


class EventService:
    """Application-level service for managing events.

    Wraps EventRepository to provide higher-level operations used by the web UI.
    """

    def __init__(self, repo: EventRepository) -> None:
        # Repository must be provided via DI
        self._repo = repo

    async def list_upcoming_events(self) -> List[Event]:
        events = await self._repo.get_upcoming()
        logger.info("EventService: list_upcoming_events count=%d", len(events))
        return events

    async def create_event(
        self,
        dto: EventCreate,
    ) -> Event:
        event_id = f"event-{uuid.uuid4()}"
        logger.info(
            "EventService: create_event id=%s title=%s when=%s place=%s price=%s",
            event_id,
            dto.title,
            dto.when.isoformat() if hasattr(dto.when, "isoformat") else str(dto.when),
            dto.place,
            str(dto.price) if dto.price is not None else "",
        )
        ev = Event(
            id=event_id,
            title=dto.title,
            when=dto.when,
            place=dto.place,
            price=dto.price,
            description=dto.description,
        )
        created = await self._repo.create(ev)
        logger.info("EventService: created id=%s", created.id)
        return created

    async def delete_event(self, event_id: str) -> bool:
        logger.info("EventService: delete_event id=%s", event_id)
        return await self._repo.delete(event_id)
