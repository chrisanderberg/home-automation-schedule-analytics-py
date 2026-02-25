"""UTC quarter index and interval splitting."""

from __future__ import annotations

from datetime import UTC, datetime

from .contracts import QuarterSpan


def _quarter_index_from_dt(dt: datetime) -> int:
    """Compute compact quarter index from a UTC datetime.

    Args:
        dt: UTC datetime inside the target quarter.

    Returns:
        Quarter index using `(year - 1970) * 4 + quarter_offset`.
    """
    if dt.tzinfo is not UTC:
        raise ValueError("dt must be UTC-aware (tzinfo=datetime.UTC)")
    quarter_number = ((dt.month - 1) // 3) + 1
    return (dt.year - 1970) * 4 + (quarter_number - 1)


def quarter_index_utc(timestamp_ms: int) -> int:
    """Return quarter index: (year - 1970) * 4 + (quarter - 1)."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return _quarter_index_from_dt(dt)


def split_interval_by_quarter_utc(start_ms: int, end_ms: int) -> list[QuarterSpan]:
    """Split [start_ms, end_ms) at UTC quarter boundaries."""
    if end_ms <= start_ms:
        raise ValueError("invalid interval")

    spans: list[QuarterSpan] = []
    cur = start_ms
    while cur < end_ms:
        dt = datetime.fromtimestamp(cur / 1000, tz=UTC)
        q_idx = _quarter_index_from_dt(dt)
        quarter_number = (q_idx % 4) + 1
        next_q_month = (quarter_number * 3) + 1
        year = dt.year
        if next_q_month == 13:
            next_q_month = 1
            year += 1
        boundary_dt = datetime(year, next_q_month, 1, tzinfo=UTC)
        boundary_ms = round(boundary_dt.timestamp() * 1000)
        if boundary_ms > end_ms:
            boundary_ms = end_ms
        spans.append(QuarterSpan(quarter_index=q_idx, start_ms=cur, end_ms=boundary_ms))
        cur = boundary_ms

    return spans
