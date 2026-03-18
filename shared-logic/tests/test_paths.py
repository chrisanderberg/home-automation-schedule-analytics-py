"""Path helper tests with lightweight real-directory scenarios where it adds clarity."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared_logic import paths


class PathsTests(unittest.TestCase):
    """Document the assumptions the runtime makes about repository layout and overrides."""

    def tearDown(self):
        paths.repository_root.cache_clear()

    def test_test_data_root_defaults_to_repo_test_data_directory(self):
        repo_root = Path("/tmp/repo-root")
        with patch.dict(os.environ, {}, clear=True):
            with patch("shared_logic.paths.repository_root", return_value=repo_root):
                self.assertEqual(paths.test_data_root(), repo_root / "test-data")

    def test_test_data_root_honors_test_data_dir_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp)
            with patch.dict(os.environ, {"TEST_DATA_DIR": str(override)}, clear=False):
                self.assertEqual(paths.test_data_root(), override.resolve())

    def test_test_data_root_rejects_missing_override_directory(self):
        missing = Path("/tmp/path-does-not-exist-for-tests")
        with patch.dict(os.environ, {"TEST_DATA_DIR": str(missing)}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                paths.test_data_root()

    def test_test_snapshot_root_uses_test_data_root(self):
        root = Path("/tmp/custom-test-data")
        with patch("shared_logic.paths.test_data_root", return_value=root):
            self.assertEqual(paths.test_snapshot_root(), root / "snapshots")

    def test_repository_root_finds_repo_from_module_path(self):
        """Use a real temp tree here so the sentinel/directory contract stays obvious."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "aggregation").mkdir()
            (repo_root / "shared-logic").mkdir()
            (repo_root / "pyproject.toml").write_text("[project]\nname='x'\n")
            nested = repo_root / "shared-logic" / "src" / "shared_logic" / "paths.py"
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.touch()

            self.assertEqual(paths._find_repo_root_from(nested), repo_root)

    def test_repository_root_finds_repo_from_current_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "aggregation").mkdir()
            (repo_root / "shared-logic").mkdir()
            (repo_root / "pyproject.toml").write_text("[project]\nname='x'\n")
            cwd_child = repo_root / "some" / "nested" / "cwd"
            cwd_child.mkdir(parents=True, exist_ok=True)
            outside_root = repo_root.parent / "outside-repo" / "paths.py"
            outside_root.parent.mkdir(parents=True, exist_ok=True)
            outside_root.touch()

            paths.repository_root.cache_clear()
            with patch("shared_logic.paths.Path.cwd", return_value=cwd_child):
                with patch("shared_logic.paths.__file__", str(outside_root)):
                    self.assertEqual(paths.repository_root(), repo_root.resolve())

    def test_find_repo_root_from_real_tree_returns_none_when_sentinel_missing(self):
        """Matching directories alone are not enough; a project sentinel must also be present."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "aggregation").mkdir()
            (repo_root / "shared-logic").mkdir()
            nested = repo_root / "shared-logic" / "src" / "shared_logic" / "paths.py"
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.touch()

            self.assertIsNone(paths._find_repo_root_from(nested))


if __name__ == "__main__":
    unittest.main()
