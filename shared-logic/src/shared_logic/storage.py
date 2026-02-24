"""SQLite storage access for controls and aggregates."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from .blob import Blob, GROUP_SIZE
from .contracts import AggregateKey, Control
from .errors import NotFoundError

logger = logging.getLogger(__name__)

AGGREGATES_DDL = """
CREATE TABLE IF NOT EXISTS aggregates (
  control_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  quarter_index INTEGER NOT NULL,
  blob BLOB NOT NULL,
  PRIMARY KEY (control_id, model_id, quarter_index),
  FOREIGN KEY (control_id) REFERENCES controls(control_id) ON DELETE RESTRICT
)
"""

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS controls (
      control_id TEXT PRIMARY KEY,
      control_type TEXT NOT NULL,
      num_states INTEGER NOT NULL,
      state_labels TEXT
    )
    """,
    AGGREGATES_DDL,
)


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with required pragmatic settings."""
    path = str(db_path)
    # Keep connections permissive for service/test usage across framework internals.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create required tables when missing."""
    for statement in SCHEMA_STATEMENTS:
        stmt = statement.strip()
        if not stmt:
            continue
        conn.execute(stmt)
    _migrate_aggregates_foreign_key(conn)


def _migrate_aggregates_foreign_key(conn: sqlite3.Connection) -> None:
    """Ensure aggregates.control_id foreign key exists for legacy databases."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='aggregates'"
        ).fetchone()
        if table_exists is None:
            conn.execute("COMMIT")
            return

        fk_rows = conn.execute("PRAGMA foreign_key_list(aggregates)").fetchall()
        has_fk = any(row[2] == "controls" and row[3] == "control_id" for row in fk_rows)
        if has_fk:
            conn.execute("COMMIT")
            return

        conn.execute("DROP TABLE IF EXISTS aggregates_old")
        conn.execute("ALTER TABLE aggregates RENAME TO aggregates_old")
        conn.execute(AGGREGATES_DDL.strip())
        dropped_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM aggregates_old
            LEFT JOIN controls ON controls.control_id = aggregates_old.control_id
            WHERE controls.control_id IS NULL
            """
        ).fetchone()[0]
        if dropped_rows > 0:
            logger.warning("dropping %d orphaned aggregate rows during foreign key migration", dropped_rows)
        conn.execute(
            """
            INSERT INTO aggregates (control_id, model_id, quarter_index, blob)
            SELECT old.control_id, old.model_id, old.quarter_index, old.blob
            FROM aggregates_old AS old
            JOIN controls ON controls.control_id = old.control_id
            """
        )
        conn.execute("DROP TABLE aggregates_old")
        conn.execute("COMMIT")
    except Exception:
        logger.exception("migration failed during aggregates fk migration")
        rollback_succeeded = False
        try:
            conn.execute("ROLLBACK")
            rollback_succeeded = True
        except Exception:
            logger.exception("rollback failed during aggregates fk migration")
        try:
            aggregates_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='aggregates'"
            ).fetchone() is not None
            aggregates_old_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='aggregates_old'"
            ).fetchone() is not None
            aggregates_row_count = 0
            has_expected_schema = False
            if aggregates_exists:
                aggregates_row_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]
                cols = conn.execute("PRAGMA table_info(aggregates)").fetchall()
                fk_rows = conn.execute("PRAGMA foreign_key_list(aggregates)").fetchall()
                has_expected_columns = [row[1] for row in cols] == [
                    "control_id",
                    "model_id",
                    "quarter_index",
                    "blob",
                ]
                has_expected_fk = any(row[2] == "controls" and row[3] == "control_id" and row[4] == "control_id" for row in fk_rows)
                has_expected_schema = has_expected_columns and has_expected_fk

            if not aggregates_old_exists:
                logger.warning(
                    "no aggregates_old table found during migration failure cleanup "
                    "(rollback_succeeded=%s, aggregates_old_exists=%s); prior rollback may have undone rename",
                    rollback_succeeded,
                    aggregates_old_exists,
                )
            elif rollback_succeeded and aggregates_exists and has_expected_schema:
                conn.execute("DROP TABLE aggregates_old")
                logger.warning(
                    "dropped aggregates_old after failed migration because aggregates appears valid "
                    "(rows=%d, expected_schema=%s)",
                    aggregates_row_count,
                    has_expected_schema,
                )
            else:
                logger.warning(
                    "preserving aggregates_old after failed migration "
                    "(rollback_succeeded=%s, aggregates_exists=%s, rows=%d, expected_schema=%s)",
                    rollback_succeeded,
                    aggregates_exists,
                    aggregates_row_count,
                    has_expected_schema,
                )
                should_restore = aggregates_exists and aggregates_row_count > 0 and not has_expected_schema
                if should_restore:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        conn.execute("DROP TABLE aggregates")
                        conn.execute("ALTER TABLE aggregates_old RENAME TO aggregates")
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                    logger.warning("restored aggregates from aggregates_old after migration failure")
        except Exception:
            logger.exception("cleanup failed while preserving/restoring aggregates_old after migration failure")
        raise


def upsert_control(conn: sqlite3.Connection, control: Control) -> None:
    """Insert or update control metadata by control_id."""
    labels: str | None = None
    if control.state_labels is not None:
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
        raise NotFoundError(f"control not found: {control_id}")

    labels: tuple[str, ...] | None = None
    if row[3] is not None:
        labels = tuple(json.loads(row[3]))

    return Control(control_id=row[0], control_type=row[1], num_states=row[2], state_labels=labels)


def _expected_blob_length(num_states: int) -> int:
    """Compute expected aggregate blob byte length for a state count.

    Args:
        num_states: Number of states configured for the control.

    Returns:
        Expected blob size in bytes.
    """
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
            control_exists = conn.execute("SELECT 1 FROM controls WHERE control_id = ?", (key.control_id,)).fetchone()
            if control_exists is None:
                raise NotFoundError(f"control not found: {key.control_id}")
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
            try:
                conn.execute("ROLLBACK")
            except Exception:
                logger.exception("rollback failed during update_aggregate")
