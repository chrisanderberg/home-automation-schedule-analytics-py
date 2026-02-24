"""Helpers for decoding JSON API response bodies."""

from __future__ import annotations

import json
from typing import Any

MAX_ERROR_BODY_CHARS = 200


def _sanitize_error_body(body: str) -> str:
    """Return a bounded, non-PII-heavy representation of an invalid payload."""
    compact = body.strip().replace("\n", " ")
    if len(compact) > MAX_ERROR_BODY_CHARS:
        return f"{compact[:MAX_ERROR_BODY_CHARS]}... (truncated)"
    return compact or "unparseable payload"


def decode_json_body(body: str, *, decode_error_as_error_payload: bool) -> dict[str, Any]:
    """Decode a JSON body with configurable fallback on decode errors."""
    if not body:
        return {}

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        if decode_error_as_error_payload:
            sanitized_body = _sanitize_error_body(body)
            return {"error": sanitized_body}
        return {}

    if isinstance(decoded, dict):
        return decoded
    return {}
