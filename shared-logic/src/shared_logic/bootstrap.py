"""Runtime bootstrap helpers shared by service entrypoints."""

from __future__ import annotations

import sys
from pathlib import Path


class RepositoryRootNotFound(RuntimeError):
    """Raised when repository root cannot be located from a starting path."""

    def __init__(self, start: Path):
        super().__init__(f"repository root not found from {start}")


def find_repo_root(start: Path) -> Path:
    """Walk upward from a path to locate the repository root.

    If start is a file, it is normalized to its parent directory before walking.
    The path is resolved (start.resolve()) before walking upward. Callers may
    safely pass Path(__file__); the function handles file inputs and returns
    a resolved directory Path representing the repository root.
    """
    if start.is_file():
        start = start.parent
    start = start.resolve()
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file() or (parent / "setup.cfg").is_file() or (parent / ".git").exists():
            return parent
    raise RepositoryRootNotFound(start)


def ensure_repo_src_paths_for_service(service_name: str, here: Path) -> None:
    """Add local src roots to sys.path for direct execution.

    Preferred input: the directory containing the entrypoint (e.g.,
    Path(__file__).parent). find_repo_root also accepts file paths and
    normalizes them to their parent before walking upward.

    Service src has higher import precedence than shared-logic.
    """
    repo_root = find_repo_root(here)
    candidates = [
        repo_root / "shared-logic" / "src",
        repo_root / service_name / "src",
    ]
    # Insert in front so the last valid candidate wins (highest precedence);
    # each sys.path.insert(0, path_str) pushes previously inserted paths right.
    for path in candidates:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)
