"""Runtime bootstrap helpers for local source-layout imports.

Local src-root insertion is delegated to the shared ensure_repo_src_paths_for_service utility.
"""

from __future__ import annotations

from pathlib import Path

from shared_logic.bootstrap import (
    RepositoryRootNotFound,
    ensure_repo_src_paths_for_service,
    find_repo_root,
)

__all__ = ["RepositoryRootNotFound", "ensure_repo_src_paths", "find_repo_root"]


def ensure_repo_src_paths() -> None:
    """Add local src roots to sys.path for direct execution."""
    ensure_repo_src_paths_for_service("reporting", Path(__file__).resolve().parent)
