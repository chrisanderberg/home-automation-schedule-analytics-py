"""Dataclass contracts shared across services."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Config",
    "Control",
    "AggregateKey",
    "HoldingInput",
    "TransitionInput",
    "BucketSpan",
    "QuarterSpan",
]


@dataclass(frozen=True)
class Config:
    """Runtime clock configuration."""

    time_zone: str
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        """Validate location bounds for clock calculations."""
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError("latitude must be in [-90, 90]")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError("longitude must be in [-180, 180]")


@dataclass(frozen=True)
class Control:
    """Control metadata for validation and blob sizing."""

    control_id: str
    control_type: str
    num_states: int
    state_labels: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Validate control metadata invariants."""
        if self.num_states < 1:
            raise ValueError("num_states must be >= 1")


@dataclass(frozen=True)
class AggregateKey:
    """Primary key for aggregate rows."""

    control_id: str
    model_id: str
    quarter_index: int


@dataclass(frozen=True)
class HoldingInput:
    """One holding interval request payload."""

    control_id: str
    model_id: str
    state: int
    start_time_ms: int
    end_time_ms: int

    def __post_init__(self) -> None:
        """Validate half-open interval shape."""
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("end_time_ms must be greater than start_time_ms")


@dataclass(frozen=True)
class TransitionInput:
    """One transition request payload."""

    control_id: str
    model_id: str
    from_state: int
    to_state: int
    timestamp_ms: int

    def __post_init__(self) -> None:
        """Validate transition input invariants."""
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if self.from_state == self.to_state:
            raise ValueError("from_state must not equal to_state")


@dataclass(frozen=True)
class BucketSpan:
    """Elapsed milliseconds attributed to one week bucket."""

    bucket: int
    millis: int

    def __post_init__(self) -> None:
        """Validate elapsed milliseconds is non-negative."""
        if self.bucket < 0:
            raise ValueError("bucket must be non-negative")
        if self.millis < 0:
            raise ValueError("millis must be non-negative")


@dataclass(frozen=True)
class QuarterSpan:
    """Interval span contained in one UTC calendar quarter."""

    quarter_index: int
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        """Validate quarter span interval shape."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
