"""Strict JSON helpers for Flask handlers."""

from __future__ import annotations

from collections.abc import Iterable

from flask import Request


class BadRequestError(ValueError):
    """Raised on malformed request payloads."""


def decode_strict_json(request: Request, required: Iterable[str], optional: Iterable[str] = ()) -> dict:
    """Decode JSON object and reject unknown or missing fields."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequestError("invalid json")

    req = set(required)
    opt = set(optional)
    allowed = req | opt

    missing = sorted(req - set(data.keys()))
    if missing:
        raise BadRequestError("missing required fields")

    unknown = sorted(set(data.keys()) - allowed)
    if unknown:
        raise BadRequestError("unknown fields")

    return data
