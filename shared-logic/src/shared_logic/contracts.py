"""Dataclass contracts shared across services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Runtime clock configuration."""

    time_zone: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Control:
    """Control metadata for validation and blob sizing."""

    control_id: str
    control_type: str
    num_states: int
    state_labels: list[str] | None = None


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


@dataclass(frozen=True)
class TransitionInput:
    """One transition request payload."""

    control_id: str
    model_id: str
    from_state: int
    to_state: int
    timestamp_ms: int


@dataclass(frozen=True)
class BucketSpan:
    """Elapsed milliseconds attributed to one week bucket."""

    bucket: int
    millis: int


@dataclass(frozen=True)
class QuarterSpan:
    """Interval span contained in one UTC calendar quarter."""

    quarter_index: int
    start_ms: int
    end_ms: int
