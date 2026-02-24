"""Snapshot export utilities shared by API and reporting flow."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .paths import snapshot_root, test_snapshot_root


def export_snapshot(conn: sqlite3.Connection) -> Path:
    """Write timestamped production snapshot under data/snapshots."""
    root = snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    out = root / f"snapshot-{ts}.sqlite"
    return _backup_to_path(conn, out)


def export_snapshot_for_test(conn: sqlite3.Connection, test_name: str, snapshot_name: str) -> Path:
    """Write deterministic test snapshot path for validation flows."""
    root = test_snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{test_name}-{snapshot_name}-snapshot.sqlite"
    return _backup_to_path(conn, out)


def _backup_to_path(conn: sqlite3.Connection, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    # Use SQLite backup API for consistent local snapshots.
    dst = sqlite3.connect(str(out_path), isolation_level=None)
    try:
        conn.backup(dst)
    finally:
        dst.close()

    wal = out_path.with_name(out_path.name + "-wal")
    shm = out_path.with_name(out_path.name + "-shm")
    for aux in (wal, shm):
        if aux.exists():
            aux.unlink()
    return out_path.resolve()


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
