"""Snapshot export utilities shared by API and reporting flow."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .paths import snapshot_root, test_snapshot_root


def export_snapshot(conn: sqlite3.Connection) -> Path:
    """Write timestamped production snapshot under data/snapshots."""
    root = snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S-%f")
    out = root / f"snapshot-{ts}.sqlite"
    return _backup_to_path(conn, out)


def export_snapshot_for_test(conn: sqlite3.Connection, test_name: str, snapshot_name: str) -> Path:
    """Write deterministic test snapshot path for validation flows."""
    safe_test_name = _validate_name_component(test_name, "test_name")
    safe_snapshot_name = _validate_name_component(snapshot_name, "snapshot_name")
    root = test_snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{safe_test_name}-{safe_snapshot_name}-snapshot.sqlite"
    return _backup_to_path(conn, out)


def _backup_to_path(conn: sqlite3.Connection, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(f"{out_path.name}.tmp-{uuid4().hex}")
    dst = sqlite3.connect(str(temp_path), isolation_level=None)
    success = False

    try:
        # Use SQLite backup API for consistent local snapshots.
        conn.backup(dst)
        dst.close()
        dst = None
        for aux in (
            temp_path.with_name(temp_path.name + "-wal"),
            temp_path.with_name(temp_path.name + "-shm"),
        ):
            if aux.exists():
                aux.unlink()
        temp_path.replace(out_path)
        success = True
    finally:
        if dst is not None:
            dst.close()
        if not success:
            if temp_path.exists():
                temp_path.unlink()
            for aux in (
                temp_path.with_name(temp_path.name + "-wal"),
                temp_path.with_name(temp_path.name + "-shm"),
            ):
                if aux.exists():
                    aux.unlink()
    return out_path.resolve()


def _validate_name_component(value: str, label: str) -> str:
    if not value:
        raise ValueError(f"{label} must be non-empty")
    if value in {".", ".."}:
        raise ValueError(f"{label} must not be relative path tokens")
    if Path(value).name != value:
        raise ValueError(f"{label} must not include path separators")
    if "/" in value or "\\" in value:
        raise ValueError(f"{label} must not include path separators")
    return value


def reset_test_db_files(db_path: Path) -> None:
    """Remove test DB and SQLite sidecar files for reset endpoint."""
    for candidate in (
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
        Path(str(db_path) + "-journal"),
    ):
        if candidate.exists():
            if candidate.is_file():
                candidate.unlink()
            elif candidate.is_dir():
                shutil.rmtree(candidate)
