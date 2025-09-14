from __future__ import annotations


class BotException(Exception):
    """Base exception for bot errors."""
    pass


class ValidationError(BotException):
    """Validation error."""
    pass


class NotFoundError(BotException):
    """Resource not found."""
    pass


class AuthenticationError(BotException):
    """Authentication failed."""
    pass


class ExternalServiceError(BotException):
    """External service error (Google Calendar, etc.)."""
    pass
