from __future__ import annotations

import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..config import settings
from ..container import container

security = HTTPBasic()


def _web_auth_enabled() -> bool:
    return bool(settings.is_web_enabled)


async def verify_web_auth(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    """Verify web interface authentication using Basic Auth.

    Denies access if the web interface is disabled or credentials are invalid.
    """
    if not _web_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Web editor disabled",
        )

    # Use constant-time comparison to mitigate timing attacks
    username_ok = (
        settings.web_username is not None and
        secrets.compare_digest(credentials.username, settings.web_username)
    )
    password_ok = (
        settings.web_password is not None and
        secrets.compare_digest(credentials.password, settings.web_password)
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Editor"'},
        )


# Service getters via DI container

def get_event_service():
    return container.event_service()


def get_location_service():
    # For now, location "service" is just the repository
    return container.location_service()


def get_quiz_service():
    # For now, quiz "service" is just the repository
    return container.quiz_service()


# Additional repository getters for DI

def get_event_repository():
    return container.event_repository()


def get_event_registration_repository():
    return container.event_registration_repository()


def get_about_repository():
    return container.about_repository()


def get_schedule_repository():
    return container.schedule_repository()


def get_metrics_service():
    return container.metrics_service()


def get_session_locations_repository():
    return container.session_locations_repository()
