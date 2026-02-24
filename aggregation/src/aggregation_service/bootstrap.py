"""Runtime bootstrap helpers for local source-layout imports."""

from __future__ import annotations

import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file() or (parent / ".git").exists():
            return parent
    raise RuntimeError(f"repository root not found from {start}")


def ensure_repo_src_paths() -> None:
    """Add local src roots to sys.path for direct execution."""
    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here)
    candidates = [
        repo_root / "shared-logic" / "src",
        repo_root / "aggregation" / "src",
        repo_root / "reporting" / "src",
    ]
    for path in reversed(candidates):
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)
