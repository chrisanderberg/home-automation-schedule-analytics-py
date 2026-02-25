"""Runtime bootstrap helpers shared by service entrypoints."""

from __future__ import annotations

import sys
from pathlib import Path


class RepositoryRootNotFound(RuntimeError):
    """Raised when repository root cannot be located from a starting path."""

    def __init__(self, start: Path):
        super().__init__(f"repository root not found from {start}")


def find_repo_root(start: Path) -> Path:
    """Walk upward from a path to locate the repository root."""
    if start.is_file():
        start = start.parent
    start = start.resolve()
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file() or (parent / ".git").exists():
            return parent
    raise RepositoryRootNotFound(start)


def ensure_repo_src_paths_for_service(service_name: str, here: Path) -> None:
    """Add local src roots to sys.path for direct execution.

    Callers must pass the directory containing the entrypoint (e.g.,
    Path(__file__).parent), not Path(__file__) itself. Passing the file path
    can trigger silent-wrong-first-iteration behavior in find_repo_root and
    lead to incorrect root discovery.

    Service src has higher import precedence than shared-logic.
    """
    repo_root = find_repo_root(here)
    candidates = [
        repo_root / "shared-logic" / "src",
        repo_root / service_name / "src",
    ]
    # Insert in order so service_name/src gets highest precedence (inserted last).
    for path in candidates:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)
