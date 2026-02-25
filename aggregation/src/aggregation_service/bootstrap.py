"""Runtime bootstrap helpers for local source-layout imports."""

from __future__ import annotations

from pathlib import Path

from shared_logic.bootstrap import (
    RepositoryRootNotFound,
    _find_repo_root as _shared_find_repo_root,
    ensure_repo_src_paths_for_service,
)

__all__ = ["RepositoryRootNotFound", "_find_repo_root", "ensure_repo_src_paths"]


def _find_repo_root(start: Path) -> Path:
    """Proxy to shared implementation for compatibility."""
    return _shared_find_repo_root(start)


def ensure_repo_src_paths() -> None:
    """Add local src roots to sys.path for direct execution."""
    ensure_repo_src_paths_for_service("aggregation", Path(__file__).resolve())
