from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from dependency_injector import containers, providers

from .bot.booking_flow import BookingFlow
from .config import settings
from .services.calendar_service import CalendarService
from .services.event_service import EventService
from .services.metrics_service import MetricsService, MetricsRepository
from .services.repositories import (
    EventRepository,
    LocationRepository,
    QuizRepository,
    UserLanguageRepository,
    AboutRepository,
    ScheduleRepository,
    BookingRepository,
    EventRegistrationRepository,
    SessionLocationsRepository,
)


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration()

    # Configuration
    config = providers.Configuration()

    # Repositories
    event_repository = providers.Singleton(EventRepository)
    location_repository = providers.Singleton(LocationRepository)
    quiz_repository = providers.Singleton(QuizRepository)
    user_language_repository = providers.Singleton(UserLanguageRepository)
    about_repository = providers.Singleton(AboutRepository)
    schedule_repository = providers.Singleton(ScheduleRepository)
    booking_repository = providers.Singleton(BookingRepository)
    event_registration_repository = providers.Singleton(EventRegistrationRepository)
    session_locations_repository = providers.Singleton(SessionLocationsRepository)

    # Services
    calendar_service = providers.Singleton(
        CalendarService,
        bookings_repo=booking_repository,
        schedule_repo=schedule_repository,
    )
    event_service = providers.Singleton(EventService, repo=event_repository)
    metrics_repository = providers.Singleton(MetricsRepository)
    metrics_service = providers.Singleton(MetricsService, repo=metrics_repository)

    # Shared thread pool executor for offloading blocking I/O
    executor = providers.Singleton(ThreadPoolExecutor, max_workers=int(os.getenv("WORKERS", "4")))

    # Aliases for simple repositories used as services in FastAPI dependencies
    location_service = providers.Singleton(LocationRepository)
    quiz_service = providers.Singleton(QuizRepository)

    # Booking flow as a singleton: stateless except for small schedule cache reused across requests
    booking_flow = providers.Singleton(
        BookingFlow,
        calendar_service=calendar_service,
        location_repo=location_repository,
    )


# Global, configured container instance
container = Container()
# Make settings available via container.config if needed by future components
try:
    container.config.from_pydantic(settings)  # type: ignore[attr-defined]
except Exception:
    # Safe fallback if pydantic is not available or misconfigured
    pass
