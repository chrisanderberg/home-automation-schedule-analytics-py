"""Slug validation helpers for testing API names."""

from __future__ import annotations

import re

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_valid_slug(value: str) -> bool:
    """Return True when value matches required lowercase slug format."""
    return bool(SLUG_PATTERN.fullmatch(value))
