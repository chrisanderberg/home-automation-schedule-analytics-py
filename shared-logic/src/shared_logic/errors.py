"""Shared error definitions."""

__all__ = ["ValidationError", "NotFoundError", "UndefinedClockError"]


class ValidationError(ValueError):
    """Raised when request input violates API/domain constraints."""

    def __init__(self, message: str, *, field: str | None = None):
        """Initialize a validation error with optional field context.

        Args:
            message: Human-readable error message.
            field: Optional request field name that failed validation.

        Returns:
            None.
        """
        super().__init__(message)
        self.field = field

    def __str__(self) -> str:
        """Return message string, appending field context when present.

        Args:
            None.

        Returns:
            Rendered error message.
        """
        message = super().__str__()
        if self.field is None:
            return message
        return f"{message} (field={self.field})"


class NotFoundError(LookupError):
    """Raised when required rows are not found in persistent storage."""


class UndefinedClockError(ValueError):
    """Raised when a clock mapping is undefined at a timestamp."""
