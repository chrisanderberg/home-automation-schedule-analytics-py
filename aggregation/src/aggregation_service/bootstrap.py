"""Runtime bootstrap helpers for local source-layout imports."""

from __future__ import annotations

import sys
from pathlib import Path


class RepositoryRootNotFound(RuntimeError):
    """Raised when repository root cannot be located from a starting path."""

    def __init__(self, start: Path):
        super().__init__(f"repository root not found from {start}")


def _find_repo_root(start: Path) -> Path:
    """Walk upward from a path to locate the repository root.

    Args:
        start: File or directory path to start searching from.

    Returns:
        Repository root path containing project sentinel files.
    """
    # Canonical implementation; keep reporting_service.bootstrap._find_repo_root aligned.
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file() or (parent / ".git").exists():
            return parent
    raise RepositoryRootNotFound(start)


def ensure_repo_src_paths() -> None:
    """Add local src roots to sys.path for direct execution."""
    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here)
    candidates = [
        repo_root / "shared-logic" / "src",
        repo_root / "aggregation" / "src",
    ]
    # First candidate should have highest import precedence.
    for path in reversed(candidates):
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)
