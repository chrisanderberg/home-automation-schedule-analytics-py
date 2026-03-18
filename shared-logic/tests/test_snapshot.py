"""Snapshot export and cleanup tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shared_logic.contracts import Control
from shared_logic.paths import repository_root
from shared_logic.snapshot import _backup_to_path, export_snapshot, export_snapshot_for_test, reset_test_db_files
from shared_logic.storage import init_schema, open_db, upsert_control


class SnapshotTests(unittest.TestCase):
    def _temp_test_root(self):
        base_test_dir = Path(os.environ.get("TEST_DATA_DIR", repository_root() / "test-data")).resolve()
        base_test_dir.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=str(base_test_dir))

    def test_export_snapshot_creates_readable_sqlite_copy(self):
        with self._temp_test_root() as tmp:
            root = Path(tmp)
            conn = open_db(root / "source.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            upsert_control(conn, Control(control_id="mode", control_type="discrete", num_states=2))
            with patch("shared_logic.snapshot.snapshot_root", return_value=root / "snapshots"):
                snapshot_path = export_snapshot(conn)

            self.assertTrue(snapshot_path.exists())
            read_conn = open_db(snapshot_path)
            self.addCleanup(read_conn.close)
            count = read_conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
            self.assertEqual(count, 1)

    def test_export_snapshot_for_test_uses_deterministic_filename(self):
        with self._temp_test_root() as tmp:
            root = Path(tmp)
            conn = open_db(root / "source.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            with patch("shared_logic.snapshot.test_snapshot_root", return_value=root / "snapshots"):
                path = export_snapshot_for_test(conn, "case-a", "baseline")

            self.assertEqual(path.name, "case-a-baseline-snapshot.sqlite")

    def test_export_snapshot_for_test_rejects_path_separators(self):
        with self._temp_test_root() as tmp:
            conn = open_db(Path(tmp) / "source.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            with self.assertRaisesRegex(ValueError, "path separators"):
                export_snapshot_for_test(conn, "case/a", "baseline")

    def test_export_snapshot_for_test_rejects_empty_name_components(self):
        with self._temp_test_root() as tmp:
            conn = open_db(Path(tmp) / "source.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            with self.assertRaisesRegex(ValueError, "non-empty"):
                export_snapshot_for_test(conn, "", "baseline")

    def test_reset_test_db_files_removes_db_and_sidecars(self):
        with self._temp_test_root() as tmp:
            db_path = Path(tmp) / "case.sqlite"
            db_path.write_bytes(b"db")
            for suffix in ("-wal", "-shm", "-journal"):
                db_path.with_name(db_path.name + suffix).write_bytes(b"sidecar")

            reset_test_db_files(db_path)

            self.assertFalse(db_path.exists())
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(db_path.with_name(db_path.name + suffix).exists())

    def test_reset_test_db_files_rejects_paths_outside_test_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "case.sqlite"
            db_path.write_bytes(b"db")

            with self.assertRaisesRegex(ValueError, "outside test data root"):
                reset_test_db_files(db_path)

            self.assertTrue(db_path.exists())

    def test_backup_to_path_cleans_up_temp_file_when_replace_fails(self):
        with self._temp_test_root() as tmp:
            root = Path(tmp)
            conn = open_db(root / "source.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            out_path = root / "snapshots" / "snapshot.sqlite"

            original_replace = Path.replace
            observed_temp_paths: list[Path] = []

            def _failing_replace(path_obj: Path, target: Path):
                observed_temp_paths.append(path_obj)
                raise OSError("replace failed")

            with patch.object(Path, "replace", autospec=True, side_effect=_failing_replace):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    _backup_to_path(conn, out_path)

            self.assertEqual(len(observed_temp_paths), 1)
            self.assertFalse(observed_temp_paths[0].exists())
            self.assertFalse(out_path.exists())

    def test_backup_to_path_cleans_up_temp_file_when_backup_fails(self):
        with self._temp_test_root() as tmp:
            root = Path(tmp)
            out_path = root / "snapshots" / "snapshot.sqlite"
            conn = Mock()

            def _failing_backup(_dst) -> None:
                temp_files = list(out_path.parent.glob("*.tmp-*"))
                self.assertEqual(len(temp_files), 1)
                temp_files[0].with_name(temp_files[0].name + "-wal").write_bytes(b"sidecar")
                raise sqlite3.Error("backup failed")

            conn.backup.side_effect = _failing_backup

            with self.assertRaisesRegex(sqlite3.Error, "backup failed"):
                _backup_to_path(conn, out_path)

            self.assertEqual(list(out_path.parent.glob("*.tmp-*")), [])
            self.assertEqual(list(out_path.parent.glob("*.tmp-*-wal")), [])
            self.assertFalse(out_path.exists())


if __name__ == "__main__":
    unittest.main()
