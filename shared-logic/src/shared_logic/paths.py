"""Path resolution utilities for runtime contracts."""

from __future__ import annotations

import importlib.resources
import os
from pathlib import Path


def _find_repo_root_from(start: Path) -> Path | None:
    for parent in start.parents:
        has_repo_dirs = (parent / "aggregation").is_dir() and (parent / "shared-logic").is_dir()
        has_sentinel = (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file()
        if has_repo_dirs and has_sentinel:
            return parent
    return None


def repository_root() -> Path:
    """Locate repository root from this module path."""
    here = Path(__file__).resolve()
    found = _find_repo_root_from(here)
    if found is not None:
        return found

    package_ref = Path(str(importlib.resources.files(__package__))).resolve()
    found = _find_repo_root_from(package_ref)
    if found is not None:
        return found

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
