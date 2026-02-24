"""Dense blob constants, index math, and value accessors."""

from __future__ import annotations

import struct

BUCKETS_PER_DAY = 288
BUCKETS_PER_WEEK = 7 * BUCKETS_PER_DAY
CLOCK_UTC = 0
CLOCK_LOCAL = 1
CLOCK_MEAN_SOLAR = 2
CLOCK_APPARENT_SOLAR = 3
CLOCK_UNEQUAL_HOURS = 4
CLOCK_COUNT = 5
GROUP_SIZE = BUCKETS_PER_WEEK * CLOCK_COUNT
MIN_STATES = 2
MAX_STATES = 10


class Blob:
    """Mutable dense u64 blob with canonical N^2 * GROUP_SIZE layout."""

    def __init__(self, num_states: int, data: bytes | bytearray | None = None) -> None:
        if num_states < MIN_STATES or num_states > MAX_STATES:
            raise ValueError("invalid num_states")
        self.num_states = num_states
        self.value_count = num_states * num_states * GROUP_SIZE
        byte_len = self.value_count * 8
        if data is None:
            self._data = bytearray(byte_len)
        else:
            if len(data) != byte_len:
                raise ValueError("blob size mismatch")
            self._data = bytearray(data)

    def to_bytes(self) -> bytes:
        """Return immutable bytes for database persistence."""
        return bytes(self._data)

    def get_u64(self, index: int) -> int:
        """Read one little-endian u64 by value index."""
        if index < 0 or index >= self.value_count:
            raise IndexError("index out of range")
        offset = index * 8
        return struct.unpack_from("<Q", self._data, offset)[0]

    def set_u64(self, index: int, value: int) -> None:
        """Write one little-endian u64 by value index."""
        if index < 0 or index >= self.value_count:
            raise IndexError("index out of range")
        if value < 0:
            raise ValueError("u64 cannot be negative")
        offset = index * 8
        struct.pack_into("<Q", self._data, offset, value)


def hold_index(state: int, clock: int, bucket: int, num_states: int) -> int:
    """Return holding index for (state, clock, bucket)."""
    if num_states < MIN_STATES or num_states > MAX_STATES:
        raise ValueError("invalid num_states")
    if state < 0 or state >= num_states:
        raise IndexError("state out of range")
    if clock < 0 or clock >= CLOCK_COUNT:
        raise IndexError("clock out of range")
    if bucket < 0 or bucket >= BUCKETS_PER_WEEK:
        raise IndexError("bucket out of range")
    return (state * GROUP_SIZE) + (clock * BUCKETS_PER_WEEK) + bucket


def trans_group_index(from_state: int, to_state: int, num_states: int) -> int:
    """Return compact transition-group index, omitting diagonal entries."""
    if num_states < MIN_STATES or num_states > MAX_STATES:
        raise ValueError("invalid num_states")
    if from_state < 0 or from_state >= num_states or to_state < 0 or to_state >= num_states:
        raise IndexError("state out of range")
    if from_state == to_state:
        raise ValueError("self transition not allowed")
    offset = to_state if to_state < from_state else to_state - 1
    return from_state * (num_states - 1) + offset


def trans_index(from_state: int, to_state: int, clock: int, bucket: int, num_states: int) -> int:
    """Return transition index for (from, to, clock, bucket)."""
    if clock < 0 or clock >= CLOCK_COUNT:
        raise IndexError("clock out of range")
    if bucket < 0 or bucket >= BUCKETS_PER_WEEK:
        raise IndexError("bucket out of range")
    group_idx = trans_group_index(from_state, to_state, num_states)
    return (num_states * GROUP_SIZE) + (group_idx * GROUP_SIZE) + (clock * BUCKETS_PER_WEEK) + bucket
