"""Strict JSON helpers for Flask handlers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from flask import Request


class BadRequestError(ValueError):
    """Raised on malformed request payloads."""


def decode_strict_json(request: Request, required: Iterable[str], optional: Iterable[str] = ()) -> dict[str, Any]:
    """Decode JSON object and reject unknown or missing fields."""
    data = request.get_json(silent=True)
    if data is None:
        if request.is_json:
            raise BadRequestError("invalid json body")
        raise BadRequestError("Content-Type must be application/json")
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
