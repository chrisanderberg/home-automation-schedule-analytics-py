"""Time-of-week bucket mapping and interval splitting for five clocks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .blob import BUCKETS_PER_DAY
from .contracts import BucketSpan
from .errors import UndefinedClockError

BUCKET_MS = 5 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
WEEK_MS = 7 * DAY_MS


@dataclass(frozen=True)
class ClockContext:
    """Clock conversion context."""

    time_zone: str
    latitude: float
    longitude: float


def _bucket_from_datetime(dt: datetime) -> int:
    """Convert a datetime into Monday-based 5-minute week bucket index.

    Args:
        dt: Timezone-aware datetime.

    Returns:
        Bucket index in `[0, BUCKETS_PER_WEEK)`.
    """
    day_index = dt.weekday()
    bucket_within_day = dt.hour * 12 + (dt.minute // 5)
    return day_index * BUCKETS_PER_DAY + bucket_within_day


def _next_boundary_utc(timestamp_ms: int) -> int:
    """Compute next UTC 5-minute bucket boundary after a timestamp.

    Args:
        timestamp_ms: UTC timestamp in milliseconds.

    Returns:
        Boundary timestamp in milliseconds.
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    minute = ((dt.minute // 5) + 1) * 5
    if minute >= 60:
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        dt = dt.replace(minute=minute, second=0, microsecond=0)
    return int(dt.timestamp() * 1000)


def _next_boundary_local(timestamp_ms: int, time_zone: str) -> int:
    """Compute next local-time 5-minute bucket boundary after a timestamp.

    Args:
        timestamp_ms: UTC timestamp in milliseconds.
        time_zone: IANA time zone name for local conversion.

    Returns:
        Boundary timestamp in milliseconds.
    """
    tz = ZoneInfo(time_zone)
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=tz)
    minute = ((dt.minute // 5) + 1) * 5
    if minute >= 60:
        boundary_dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        boundary_dt = dt.replace(minute=minute, second=0, microsecond=0)
    boundary_ms = int(boundary_dt.timestamp() * 1000)
    if boundary_ms <= timestamp_ms:
        return timestamp_ms + BUCKET_MS
    return boundary_ms


def bucket_at_utc(timestamp_ms: int) -> int:
    """Map UTC timestamp to Monday-based 5-minute bucket."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return _bucket_from_datetime(dt)


def bucket_at_local(timestamp_ms: int, time_zone: str) -> int:
    """Map timestamp to bucket in configured local zone."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=ZoneInfo(time_zone))
    return _bucket_from_datetime(dt)


def split_interval_utc(start_ms: int, end_ms: int) -> list[BucketSpan]:
    """Split [start_ms, end_ms) in UTC bucket coordinates."""
    if end_ms <= start_ms:
        raise ValueError("invalid interval")
    spans: list[BucketSpan] = []
    cur = start_ms
    while cur < end_ms:
        bucket = bucket_at_utc(cur)
        boundary = min(end_ms, _next_boundary_utc(cur))
        millis = boundary - cur
        if millis <= 0:
            raise ValueError("invalid interval")
        spans.append(BucketSpan(bucket=bucket, millis=millis))
        cur = boundary
    return spans


def split_interval_local(start_ms: int, end_ms: int, time_zone: str) -> list[BucketSpan]:
    """Split [start_ms, end_ms) in local-time bucket coordinates."""
    if end_ms <= start_ms:
        raise ValueError("invalid interval")
    spans: list[BucketSpan] = []
    cur = start_ms
    while cur < end_ms:
        bucket = bucket_at_local(cur, time_zone)
        boundary = min(end_ms, _next_boundary_local(cur, time_zone))
        millis = boundary - cur
        if millis <= 0:
            raise ValueError("invalid interval")
        spans.append(BucketSpan(bucket=bucket, millis=millis))
        cur = boundary
    return spans


def _validate_coordinates(latitude: float, longitude: float) -> None:
    """Validate latitude/longitude input bounds and finiteness.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.

    Returns:
        None.
    """
    if math.isnan(latitude) or math.isnan(longitude) or math.isinf(latitude) or math.isinf(longitude):
        raise ValueError("invalid coordinates")
    if latitude > 90 or latitude < -90 or longitude > 180 or longitude < -180:
        raise ValueError("invalid coordinates")


def _duration_ms_from_offset_minutes(offset_minutes: float) -> int:
    """Convert a minute offset into milliseconds.

    Args:
        offset_minutes: Minute offset from UTC.

    Returns:
        Offset duration in milliseconds.
    """
    return int(offset_minutes * 60 * 1000)


def _fractional_year(day: datetime) -> float:
    """Compute NOAA-style fractional year angle (radians).

    Args:
        day: UTC datetime used for solar equations.

    Returns:
        Fractional year angle `gamma` in radians.
    """
    yday = day.timetuple().tm_yday
    return 2 * math.pi / 365 * ((yday - 1) + ((day.hour - 12) / 24))


def _equation_of_time_minutes(day: datetime) -> float:
    """Compute equation-of-time correction in minutes.

    Args:
        day: UTC datetime used for solar equations.

    Returns:
        Equation-of-time offset in minutes.
    """
    gamma = _fractional_year(day)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def _solar_declination(day: datetime) -> float:
    """Compute solar declination angle (radians).

    Args:
        day: UTC datetime used for solar equations.

    Returns:
        Solar declination in radians.
    """
    gamma = _fractional_year(day)
    return (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )


def _sunrise_sunset_solar_minutes(day: datetime, latitude: float) -> tuple[float, float]:
    """Compute sunrise and sunset in solar minutes for a UTC day.

    Args:
        day: UTC midnight for the day being evaluated.
        latitude: Latitude in decimal degrees.

    Returns:
        Tuple `(sunrise_minutes, sunset_minutes)` in solar-time minutes.
    """
    decl = _solar_declination(day)
    lat_rad = latitude * math.pi / 180
    solar_zenith = 90.833 * math.pi / 180
    cos_h = (math.cos(solar_zenith) / (math.cos(lat_rad) * math.cos(decl))) - (math.tan(lat_rad) * math.tan(decl))
    if cos_h > 1 or cos_h < -1:
        raise UndefinedClockError("clock mapping undefined")
    h = math.acos(cos_h)
    h_deg = h * 180 / math.pi
    sunrise = 720 - 4 * h_deg
    sunset = 720 + 4 * h_deg
    return sunrise, sunset


def _split_interval_with_offset(
    start_ms: int, end_ms: int, offset_minutes_func: Callable[[int], float]
) -> list[BucketSpan]:
    """Split an interval using UTC buckets after applying dynamic time offset.

    Args:
        start_ms: Inclusive UTC start timestamp in milliseconds.
        end_ms: Exclusive UTC end timestamp in milliseconds.
        offset_minutes_func: Callable returning offset minutes for a timestamp.

    Returns:
        List of bucket spans in adjusted-clock coordinates.
    """
    if end_ms <= start_ms:
        raise ValueError("invalid interval")
    spans: list[BucketSpan] = []
    cur = start_ms
    while cur < end_ms:
        offset_minutes = offset_minutes_func(cur)
        adj_ms = cur + _duration_ms_from_offset_minutes(offset_minutes)
        bucket = bucket_at_utc(adj_ms)

        adj_boundary = _next_boundary_utc(adj_ms)
        boundary_utc = adj_boundary - _duration_ms_from_offset_minutes(offset_minutes)
        if boundary_utc <= cur:
            boundary_utc = cur + BUCKET_MS
        boundary_utc = min(boundary_utc, end_ms)

        millis = boundary_utc - cur
        if millis <= 0:
            raise ValueError("invalid interval")

        spans.append(BucketSpan(bucket=bucket, millis=millis))
        cur = boundary_utc
    return spans


def bucket_at_mean_solar(timestamp_ms: int, latitude: float, longitude: float) -> int:
    """Map timestamp to mean-solar week bucket."""
    _validate_coordinates(latitude, longitude)
    adj_ms = timestamp_ms + _duration_ms_from_offset_minutes(longitude * 4)
    return bucket_at_utc(adj_ms)


def bucket_at_apparent_solar(timestamp_ms: int, latitude: float, longitude: float) -> int:
    """Map timestamp to apparent-solar week bucket."""
    _validate_coordinates(latitude, longitude)
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    offset_minutes = longitude * 4 + _equation_of_time_minutes(dt)
    adj_ms = timestamp_ms + _duration_ms_from_offset_minutes(offset_minutes)
    return bucket_at_utc(adj_ms)


def bucket_at_unequal_hours(timestamp_ms: int, latitude: float, longitude: float) -> int:
    """Map timestamp to unequal-hours bucket (raises UndefinedClockError near polar extremes)."""
    _validate_coordinates(latitude, longitude)
    return _bucket_at_unequal_hours_unchecked(timestamp_ms, latitude, longitude)


def _bucket_at_unequal_hours_unchecked(timestamp_ms: int, latitude: float, longitude: float) -> int:
    """Map timestamp to unequal-hours bucket without coordinate validation.

    Args:
        timestamp_ms: UTC timestamp in milliseconds.
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.

    Returns:
        Unequal-hours bucket index.
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    offset_minutes = longitude * 4 + _equation_of_time_minutes(dt)
    adj = dt + timedelta(minutes=offset_minutes)

    day_start = datetime(adj.year, adj.month, adj.day, tzinfo=UTC)
    solar_minutes = (adj - day_start).total_seconds() / 60
    if solar_minutes < 0:
        solar_minutes += 1440

    sunrise, sunset = _sunrise_sunset_solar_minutes(day_start, latitude)
    day_length = sunset - sunrise
    night_length = 1440 - day_length
    if day_length <= 0 or night_length <= 0:
        raise UndefinedClockError("clock mapping undefined")

    if sunrise <= solar_minutes < sunset:
        day_fraction = (solar_minutes - sunrise) / day_length
        pseudo_minutes = 360 + day_fraction * 720
    else:
        if solar_minutes >= sunset:
            night_fraction = (solar_minutes - sunset) / night_length
        else:
            night_fraction = (solar_minutes + 1440 - sunset) / night_length
        pseudo_minutes = 1080 + night_fraction * 720
        if pseudo_minutes >= 1440:
            pseudo_minutes -= 1440

    bucket_within_day = int(pseudo_minutes) // 5
    day_index = adj.weekday()
    return day_index * BUCKETS_PER_DAY + bucket_within_day


def _next_unequal_boundary(timestamp_ms: int, latitude: float, longitude: float) -> int:
    """Find next unequal-hours bucket boundary after a timestamp.

    Args:
        timestamp_ms: UTC timestamp in milliseconds.
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.

    Returns:
        Boundary timestamp in milliseconds.
    """
    _validate_coordinates(latitude, longitude)
    start_bucket = _bucket_at_unequal_hours_unchecked(timestamp_ms, latitude, longitude)
    low = timestamp_ms
    probe = timestamp_ms + 60 * 1000
    for _ in range(400):
        probe_bucket = _bucket_at_unequal_hours_unchecked(probe, latitude, longitude)
        if probe_bucket != start_bucket:
            hi = probe
            while hi - low > 1:
                mid = low + ((hi - low) // 2)
                mid_bucket = _bucket_at_unequal_hours_unchecked(mid, latitude, longitude)
                if mid_bucket == start_bucket:
                    low = mid
                else:
                    hi = mid
            if hi <= timestamp_ms:
                return timestamp_ms + BUCKET_MS
            return hi
        low = probe
        probe += 60 * 1000
    raise ValueError("could not locate next bucket boundary within probe limit")


def split_interval_mean_solar(start_ms: int, end_ms: int, latitude: float, longitude: float) -> list[BucketSpan]:
    """Split [start_ms, end_ms) in mean-solar bucket coordinates."""
    _validate_coordinates(latitude, longitude)
    return _split_interval_with_offset(start_ms, end_ms, lambda _ts: longitude * 4)


def split_interval_apparent_solar(start_ms: int, end_ms: int, latitude: float, longitude: float) -> list[BucketSpan]:
    """Split [start_ms, end_ms) in apparent-solar bucket coordinates."""
    _validate_coordinates(latitude, longitude)
    return _split_interval_with_offset(
        start_ms,
        end_ms,
        lambda ts: longitude * 4 + _equation_of_time_minutes(datetime.fromtimestamp(ts / 1000, tz=UTC)),
    )


def split_interval_unequal_hours(start_ms: int, end_ms: int, latitude: float, longitude: float) -> list[BucketSpan]:
    """Split [start_ms, end_ms) in unequal-hours bucket coordinates."""
    _validate_coordinates(latitude, longitude)
    if end_ms <= start_ms:
        raise ValueError("invalid interval")
    spans: list[BucketSpan] = []
    cur = start_ms
    while cur < end_ms:
        bucket = bucket_at_unequal_hours(cur, latitude, longitude)
        boundary = _next_unequal_boundary(cur, latitude, longitude)
        boundary = min(boundary, end_ms)
        millis = boundary - cur
        if millis <= 0:
            raise ValueError("invalid interval")
        spans.append(BucketSpan(bucket=bucket, millis=millis))
        cur = boundary
    return spans
