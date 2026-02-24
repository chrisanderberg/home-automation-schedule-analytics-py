"""Path resolution utilities for runtime contracts."""

import os
from pathlib import Path


def _find_repo_root_from(start: Path) -> Path | None:
    """Walk upward from a path and locate repository root if present.

    Args:
        start: File or directory path used as search starting point.

    Returns:
        Repository root path when found, otherwise `None`.
    """
    for parent in (start, *start.parents):
        has_repo_dirs = (parent / "aggregation").is_dir() and (parent / "shared-logic").is_dir()
        has_sentinel = (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file()
        if has_repo_dirs and has_sentinel:
            return parent
    return None


def repository_root() -> Path:
    """Locate repository root from this module path."""
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        found = _find_repo_root_from(start)
        if found is not None:
            return found
    raise RuntimeError("repository root not found from module path or current working directory")


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
        override_path = Path(override).resolve()
        if not override_path.exists() or not override_path.is_dir():
            raise RuntimeError(
                f"TEST_DATA_DIR does not exist or is not a directory: provided={override!r} resolved={override_path}"
            )
        return override_path
    return repository_root() / "test-data"


def test_snapshot_root() -> Path:
    """Return testing snapshot root."""
    return test_data_root() / "snapshots"
