"""SQLite storage access for controls and aggregates."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from .blob import Blob, GROUP_SIZE
from .contracts import AggregateKey, Control
from .errors import NotFoundError

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS controls (
  control_id TEXT PRIMARY KEY,
  control_type TEXT NOT NULL,
  num_states INTEGER NOT NULL,
  state_labels TEXT
);

CREATE TABLE IF NOT EXISTS aggregates (
  control_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  quarter_index INTEGER NOT NULL,
  blob BLOB NOT NULL,
  PRIMARY KEY (control_id, model_id, quarter_index)
);
"""


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with required pragmatic settings."""
    path = str(db_path)
    # Main API server handles requests on a different thread than startup.
    # Disable thread affinity checks so one long-lived connection can be reused.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create required tables when missing."""
    conn.executescript(SCHEMA_SQL)


def upsert_control(conn: sqlite3.Connection, control: Control) -> None:
    """Insert or update control metadata by control_id."""
    labels: str | None = None
    if control.state_labels:
        labels = json.dumps(control.state_labels)
    conn.execute(
        """
        INSERT INTO controls (control_id, control_type, num_states, state_labels)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(control_id) DO UPDATE SET
            control_type=excluded.control_type,
            num_states=excluded.num_states,
            state_labels=excluded.state_labels
        """,
        (control.control_id, control.control_type, control.num_states, labels),
    )


def get_control(conn: sqlite3.Connection, control_id: str) -> Control:
    """Load control metadata for validation and ingestion."""
    row = conn.execute(
        "SELECT control_id, control_type, num_states, state_labels FROM controls WHERE control_id = ?",
        (control_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("control not found")

    labels: list[str] | None = None
    if row[3]:
        labels = json.loads(row[3])

    return Control(control_id=row[0], control_type=row[1], num_states=row[2], state_labels=labels)


def _expected_blob_length(num_states: int) -> int:
    return num_states * num_states * GROUP_SIZE * 8


def update_aggregate(conn: sqlite3.Connection, key: AggregateKey, num_states: int, update_fn: Callable[[Blob], None]) -> None:
    """Read-modify-write aggregate row under BEGIN IMMEDIATE."""
    conn.execute("BEGIN IMMEDIATE")
    committed = False
    try:
        row = conn.execute(
            "SELECT blob FROM aggregates WHERE control_id=? AND model_id=? AND quarter_index=?",
            (key.control_id, key.model_id, key.quarter_index),
        ).fetchone()

        if row is None:
            blob = Blob(num_states)
        else:
            raw = row[0]
            if len(raw) != _expected_blob_length(num_states):
                raise ValueError("aggregate blob size mismatch")
            blob = Blob(num_states, raw)

        update_fn(blob)

        conn.execute(
            """
            INSERT INTO aggregates (control_id, model_id, quarter_index, blob)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(control_id, model_id, quarter_index) DO UPDATE SET blob=excluded.blob
            """,
            (key.control_id, key.model_id, key.quarter_index, blob.to_bytes()),
        )
        conn.execute("COMMIT")
        committed = True
    finally:
        if not committed:
            conn.execute("ROLLBACK")
