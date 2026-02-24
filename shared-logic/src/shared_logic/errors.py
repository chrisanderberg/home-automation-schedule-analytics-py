"""Shared error definitions."""


class ValidationError(ValueError):
    """Raised when request input violates API/domain constraints."""


class NotFoundError(LookupError):
    """Raised when required rows are not found in persistent storage."""


class UndefinedClockError(ValueError):
    """Raised when a clock mapping is undefined at a timestamp."""
