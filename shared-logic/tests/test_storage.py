"""Storage and migration tests focused on sqlite failure modes and invariants."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared_logic.blob import Blob
from shared_logic.contracts import AggregateKey, Control
from shared_logic.errors import NotFoundError
from shared_logic.storage import get_control, init_schema, open_db, update_aggregate, upsert_control


class StorageTests(unittest.TestCase):
    """Keep the persistence layer readable by testing success and rollback paths directly."""

    def _temp_db_with_schema(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = open_db(Path(tmp.name) / "storage.sqlite")
        self.addCleanup(conn.close)
        init_schema(conn)
        return conn

    def test_upsert_and_get_control_roundtrip_with_state_labels(self):
        """State labels are easy to drop accidentally because they are JSON-encoded in sqlite."""
        conn = self._temp_db_with_schema()

        control = Control(
            control_id="mode",
            control_type="discrete",
            num_states=3,
            state_labels=("away", "home", "sleep"),
        )
        upsert_control(conn, control)

        loaded = get_control(conn, "mode")
        self.assertEqual(loaded, control)

    def test_get_control_raises_not_found_for_missing_control(self):
        conn = self._temp_db_with_schema()

        with self.assertRaises(NotFoundError):
            get_control(conn, "missing")

    def test_update_aggregate_rolls_back_when_update_fn_raises(self):
        """A failed aggregate mutation must not leave behind a partially created row."""
        conn = self._temp_db_with_schema()
        upsert_control(conn, Control(control_id="mode", control_type="discrete", num_states=2))

        key = AggregateKey(control_id="mode", model_id="m1", quarter_index=42)

        def _boom(_blob: Blob) -> None:
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            update_aggregate(conn, key, 2, _boom)

        row = conn.execute(
            "SELECT COUNT(*) FROM aggregates WHERE control_id=? AND model_id=? AND quarter_index=?",
            (key.control_id, key.model_id, key.quarter_index),
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_update_aggregate_rejects_blob_size_mismatch(self):
        conn = self._temp_db_with_schema()
        upsert_control(conn, Control(control_id="mode", control_type="discrete", num_states=2))

        key = AggregateKey(control_id="mode", model_id="m1", quarter_index=42)
        conn.execute(
            "INSERT INTO aggregates (control_id, model_id, quarter_index, blob) VALUES (?, ?, ?, ?)",
            (key.control_id, key.model_id, key.quarter_index, b"bad"),
        )

        with self.assertRaisesRegex(ValueError, "blob size mismatch"):
            update_aggregate(conn, key, 2, lambda blob: blob.set_u64(0, 1))

    def test_update_aggregate_creates_row_for_existing_control(self):
        conn = self._temp_db_with_schema()
        upsert_control(conn, Control(control_id="mode", control_type="discrete", num_states=2))

        key = AggregateKey(control_id="mode", model_id="m1", quarter_index=42)

        def _update(blob: Blob) -> None:
            blob.set_u64(0, 99)

        update_aggregate(conn, key, 2, _update)

        raw = conn.execute(
            "SELECT blob FROM aggregates WHERE control_id=? AND model_id=? AND quarter_index=?",
            (key.control_id, key.model_id, key.quarter_index),
        ).fetchone()[0]
        self.assertEqual(Blob(2, raw).get_u64(0), 99)

    def test_init_schema_migrates_legacy_aggregates_table_with_foreign_key(self):
        """This protects upgrades from silently leaving old schemas in place."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite"
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            self.addCleanup(conn.close)
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE controls (
                  control_id TEXT PRIMARY KEY,
                  control_type TEXT NOT NULL,
                  num_states INTEGER NOT NULL,
                  state_labels TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE aggregates (
                  control_id TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  quarter_index INTEGER NOT NULL,
                  blob BLOB NOT NULL,
                  PRIMARY KEY (control_id, model_id, quarter_index)
                )
                """
            )
            conn.execute(
                "INSERT INTO controls (control_id, control_type, num_states, state_labels) VALUES (?, ?, ?, ?)",
                ("mode", "discrete", 2, None),
            )
            conn.execute(
                "INSERT INTO aggregates (control_id, model_id, quarter_index, blob) VALUES (?, ?, ?, ?)",
                ("mode", "m1", 42, Blob(2).to_bytes()),
            )

            init_schema(conn)

            fk_rows = conn.execute("PRAGMA foreign_key_list(aggregates)").fetchall()
            self.assertTrue(
                any(row[2] == "controls" and row[3] == "control_id" for row in fk_rows),
                "aggregates foreign key to controls was not added",
            )

            row_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]
            self.assertEqual(row_count, 1)

    def test_init_schema_drops_orphaned_aggregate_rows_during_migration(self):
        """Legacy orphan rows should be removed so the migrated table satisfies the new FK."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite"
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            self.addCleanup(conn.close)
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE controls (
                  control_id TEXT PRIMARY KEY,
                  control_type TEXT NOT NULL,
                  num_states INTEGER NOT NULL,
                  state_labels TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE aggregates (
                  control_id TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  quarter_index INTEGER NOT NULL,
                  blob BLOB NOT NULL,
                  PRIMARY KEY (control_id, model_id, quarter_index)
                )
                """
            )
            conn.execute(
                "INSERT INTO controls (control_id, control_type, num_states, state_labels) VALUES (?, ?, ?, ?)",
                ("kept", "discrete", 2, None),
            )
            conn.execute(
                "INSERT INTO aggregates (control_id, model_id, quarter_index, blob) VALUES (?, ?, ?, ?)",
                ("kept", "m1", 42, Blob(2).to_bytes()),
            )
            conn.execute(
                "INSERT INTO aggregates (control_id, model_id, quarter_index, blob) VALUES (?, ?, ?, ?)",
                ("orphaned", "m1", 43, Blob(2).to_bytes()),
            )

            init_schema(conn)

            control_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT control_id FROM aggregates ORDER BY quarter_index"
                ).fetchall()
            ]
            self.assertEqual(control_ids, ["kept"])


if __name__ == "__main__":
    unittest.main()
