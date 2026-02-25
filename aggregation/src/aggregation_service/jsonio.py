"""Strict JSON helpers for Flask handlers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from flask import Request
from werkzeug.exceptions import BadRequest


class BadRequestError(ValueError):
    """Raised on malformed request payloads."""


def decode_strict_json(request: Request, required: Iterable[str], optional: Iterable[str] = ()) -> dict[str, Any]:
    """Decode JSON object and reject unknown or missing fields."""
    if request.mimetype != "application/json":
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
