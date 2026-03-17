"""Strict JSON helpers for Flask handlers.

The API intentionally rejects unknown keys so request contracts stay explicit
and backwards-incompatible payload changes fail loudly.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from flask import Request
from werkzeug.exceptions import BadRequest


class BadRequestError(ValueError):
    """Raised on malformed request payloads."""


def decode_strict_json(request: Request, required: Iterable[str], optional: Iterable[str] = ()) -> dict[str, Any]:
    """Decode a JSON object and reject unknown or missing fields.

    This keeps the Flask boundary narrow: handlers receive a dictionary whose
    shape is already checked against the endpoint contract.
    """
    if not request.is_json:
        raise BadRequestError("Content-Type must be application/json")
    try:
        data = request.get_json(silent=False)
    except (json.JSONDecodeError, UnicodeDecodeError, BadRequest) as exc:
        raise BadRequestError("invalid json body") from exc
    if not isinstance(data, dict):
        raise BadRequestError("JSON payload must be an object")

    req = set(required)
    opt = set(optional)
    allowed = req | opt

    keys = set(data.keys())
    missing = sorted(req - keys)
    if missing:
        raise BadRequestError(f"missing required fields: {missing}")

    unknown = sorted(keys - allowed)
    if unknown:
        raise BadRequestError(f"unknown fields: {unknown}")

    return data
