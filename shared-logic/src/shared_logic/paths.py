"""Path resolution utilities for runtime contracts."""

from __future__ import annotations

import os
from pathlib import Path


def repository_root() -> Path:
    """Locate repository root from this module path."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "aggregation").is_dir() and (parent / "shared-logic").is_dir():
            return parent
    raise RuntimeError(f"repository root not found from {here}")


def data_root() -> Path:
    """Return production data root."""
    return repository_root() / "data"


def snapshot_root() -> Path:
    """Return production snapshot root."""
    return data_root() / "snapshots"


def test_data_root() -> Path:
    """Return test data root using TEST_DATA_DIR override when set."""
    override = os.getenv("TEST_DATA_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return repository_root() / "test-data"


def test_snapshot_root() -> Path:
    """Return testing snapshot root."""
    return test_data_root() / "snapshots"
