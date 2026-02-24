"""Helpers for decoding JSON API response bodies."""

from __future__ import annotations

import json
from typing import Any

MAX_ERROR_BODY_CHARS = 200
TRUNCATION_SUFFIX = "... (truncated)"


def _sanitize_error_body(body: str) -> str:
    """Return a bounded representation of invalid payload text (no PII redaction)."""
    compact = " ".join(body.splitlines()).strip()
    if len(compact) > MAX_ERROR_BODY_CHARS:
        prefix_len = max(0, MAX_ERROR_BODY_CHARS - len(TRUNCATION_SUFFIX))
        return f"{compact[:prefix_len]}{TRUNCATION_SUFFIX}"
    return compact or "unparseable payload"


def decode_json_body(body: str, *, decode_error_as_error_payload: bool) -> Any:
    """Decode a JSON body with configurable fallback on decode errors."""
    if not body:
        if decode_error_as_error_payload:
            return {"error": ""}
        raise ValueError("invalid JSON body")

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        if decode_error_as_error_payload:
            sanitized_body = _sanitize_error_body(body)
            return {"error": sanitized_body}
        raise ValueError("invalid JSON body")

    return decoded
