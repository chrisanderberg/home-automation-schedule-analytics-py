"""Strict JSON helpers for Flask handlers."""

from __future__ import annotations

from collections.abc import Iterable

from flask import Request


class BadRequestError(ValueError):
    """Raised on malformed request payloads."""


def decode_strict_json(request: Request, required: Iterable[str], optional: Iterable[str] = ()) -> dict:
    """Decode JSON object and reject unknown or missing fields."""
    if not request.is_json:
        probe = request.get_json(force=True, silent=True)
        if probe is None:
            raise BadRequestError("Content-Type must be application/json")
    try:
        data = request.get_json(force=True)
    except Exception as exc:  # pragma: no cover - flask parser differences
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
