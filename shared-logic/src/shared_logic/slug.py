"""Slug validation helpers for names exposed in API payloads and filenames."""

import re

SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def is_valid_slug(value: str) -> bool:
    """Return ``True`` when ``value`` matches the lowercase dash-separated format."""
    return bool(SLUG_PATTERN.fullmatch(value))
