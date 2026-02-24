"""Runtime bootstrap helpers for local source-layout imports."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_src_paths() -> None:
    """Add local src roots to sys.path for direct execution."""
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    candidates = [
        repo_root / "shared-logic" / "src",
        repo_root / "reporting" / "src",
        repo_root / "aggregation" / "src",
    ]
    for path in candidates:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)
