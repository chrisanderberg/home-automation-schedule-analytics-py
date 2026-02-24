"""Ingestion orchestration for holding and transition events."""

from __future__ import annotations

import sqlite3

from .blob import (
    CLOCK_APPARENT_SOLAR,
    CLOCK_LOCAL,
    CLOCK_MEAN_SOLAR,
    CLOCK_UTC,
    CLOCK_UNEQUAL_HOURS,
    hold_index,
    trans_index,
)
from .bucketing import (
    bucket_at_apparent_solar,
    bucket_at_local,
    bucket_at_mean_solar,
    bucket_at_unequal_hours,
    bucket_at_utc,
    split_interval_apparent_solar,
    split_interval_local,
    split_interval_mean_solar,
    split_interval_unequal_hours,
    split_interval_utc,
)
from .contracts import AggregateKey, Config, HoldingInput, TransitionInput
from .errors import NotFoundError, UndefinedClockError, ValidationError
from .quarter import quarter_index_utc, split_interval_utc as split_quarter_interval_utc
from .storage import get_control, update_aggregate


def _validate_holding(input_data: HoldingInput) -> None:
    if not input_data.control_id or not input_data.model_id:
        raise ValidationError("invalid input")
    if input_data.state < 0:
        raise ValidationError("invalid input")
    if input_data.end_time_ms <= input_data.start_time_ms:
        raise ValidationError("invalid input")


def _validate_transition(input_data: TransitionInput) -> None:
    if not input_data.control_id or not input_data.model_id:
        raise ValidationError("invalid input")
    if input_data.from_state < 0 or input_data.to_state < 0:
        raise ValidationError("invalid input")
    if input_data.from_state == input_data.to_state:
        raise ValidationError("invalid input")


def ingest_holding(conn: sqlite3.Connection, cfg: Config, input_data: HoldingInput) -> None:
    """Ingest one holding interval across quarter and five-clock bucket splits."""
    _validate_holding(input_data)

    try:
        control = get_control(conn, input_data.control_id)
    except NotFoundError as exc:
        raise ValidationError("unknown control") from exc

    if input_data.state >= control.num_states:
        raise ValidationError("invalid input")

    quarter_spans = split_quarter_interval_utc(input_data.start_time_ms, input_data.end_time_ms)

    for q_span in quarter_spans:
        key = AggregateKey(control_id=input_data.control_id, model_id=input_data.model_id, quarter_index=q_span.quarter_index)

        def _update(blob) -> None:
            splitters = [
                (CLOCK_UTC, lambda: split_interval_utc(q_span.start_ms, q_span.end_ms)),
                (CLOCK_LOCAL, lambda: split_interval_local(q_span.start_ms, q_span.end_ms, cfg.time_zone)),
                (
                    CLOCK_MEAN_SOLAR,
                    lambda: split_interval_mean_solar(q_span.start_ms, q_span.end_ms, cfg.latitude, cfg.longitude),
                ),
                (
                    CLOCK_APPARENT_SOLAR,
                    lambda: split_interval_apparent_solar(q_span.start_ms, q_span.end_ms, cfg.latitude, cfg.longitude),
                ),
                (
                    CLOCK_UNEQUAL_HOURS,
                    lambda: split_interval_unequal_hours(q_span.start_ms, q_span.end_ms, cfg.latitude, cfg.longitude),
                ),
            ]

            for clock_idx, split_fn in splitters:
                try:
                    spans = split_fn()
                except UndefinedClockError:
                    continue
                for span in spans:
                    idx = hold_index(input_data.state, clock_idx, span.bucket, control.num_states)
                    current = blob.get_u64(idx)
                    blob.set_u64(idx, current + span.millis)

        update_aggregate(conn, key, control.num_states, _update)


def ingest_transition(conn: sqlite3.Connection, cfg: Config, input_data: TransitionInput) -> None:
    """Ingest one transition event into all defined clock buckets."""
    _validate_transition(input_data)

    try:
        control = get_control(conn, input_data.control_id)
    except NotFoundError as exc:
        raise ValidationError("unknown control") from exc

    if input_data.from_state >= control.num_states or input_data.to_state >= control.num_states:
        raise ValidationError("invalid input")

    q_idx = quarter_index_utc(input_data.timestamp_ms)
    key = AggregateKey(control_id=input_data.control_id, model_id=input_data.model_id, quarter_index=q_idx)

    def _update(blob) -> None:
        bucket_fns = [
            (CLOCK_UTC, lambda: bucket_at_utc(input_data.timestamp_ms)),
            (CLOCK_LOCAL, lambda: bucket_at_local(input_data.timestamp_ms, cfg.time_zone)),
            (
                CLOCK_MEAN_SOLAR,
                lambda: bucket_at_mean_solar(input_data.timestamp_ms, cfg.latitude, cfg.longitude),
            ),
            (
                CLOCK_APPARENT_SOLAR,
                lambda: bucket_at_apparent_solar(input_data.timestamp_ms, cfg.latitude, cfg.longitude),
            ),
            (
                CLOCK_UNEQUAL_HOURS,
                lambda: bucket_at_unequal_hours(input_data.timestamp_ms, cfg.latitude, cfg.longitude),
            ),
        ]

        for clock_idx, bucket_fn in bucket_fns:
            try:
                bucket = bucket_fn()
            except UndefinedClockError:
                continue
            idx = trans_index(input_data.from_state, input_data.to_state, clock_idx, bucket, control.num_states)
            current = blob.get_u64(idx)
            blob.set_u64(idx, current + 1)

    update_aggregate(conn, key, control.num_states, _update)
