"""Helpers for decoding JSON API response bodies."""

from __future__ import annotations

import json
from typing import Any


def decode_json_body(body: str, *, decode_error_as_error_payload: bool) -> dict[str, Any]:
    """Decode a JSON body with configurable fallback on decode errors."""
    if not body:
        return {}

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        if decode_error_as_error_payload:
            return {"error": body}
        return {}

    if isinstance(decoded, dict):
        return decoded
    return {}
