"""Shared error definitions."""

__all__ = ["ValidationError", "NotFoundError", "UndefinedClockError"]


class ValidationError(ValueError):
    """Raised when request input violates API/domain constraints."""

    def __init__(self, message: str, *, field: str | None = None):
        super().__init__(message)
        self.field = field


class NotFoundError(LookupError):
    """Raised when required rows are not found in persistent storage."""


class UndefinedClockError(ValueError):
    """Raised when a clock mapping is undefined at a timestamp."""
