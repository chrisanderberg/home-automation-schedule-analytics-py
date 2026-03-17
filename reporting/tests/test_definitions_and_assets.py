"""Dagster wiring, asset-behavior, and regression tests for reporting."""

from __future__ import annotations

import io
import importlib
import importlib.util
import os
import sqlite3
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_DAGSTER = importlib.util.find_spec("dagster") is not None

if HAS_DAGSTER:
    from dagster import Failure, build_asset_context

    import reporting_service.assets as assets
    import reporting_service.definitions as definitions_module


@unittest.skipUnless(HAS_DAGSTER, "dagster is required for reporting Dagster tests")
class ReportingDagsterTests(unittest.TestCase):
    def _quiet_asset_context(self):
        """Build an asset context that tests can patch to suppress expected log noise."""
        return build_asset_context()

    def _write_snapshot(self, root: Path, name: str, *, controls: int, aggregates: int) -> Path:
        """Create the smallest sqlite snapshot shape the assets know how to read."""
        path = root / name
        with sqlite3.connect(str(path)) as conn:
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
            for idx in range(controls):
                conn.execute(
                    "INSERT INTO controls (control_id, control_type, num_states, state_labels) VALUES (?, ?, ?, ?)",
                    (f"c{idx}", "discrete", 2, None),
                )
            for idx in range(aggregates):
                conn.execute(
                    "INSERT INTO aggregates (control_id, model_id, quarter_index, blob) VALUES (?, ?, ?, ?)",
                    (f"c{idx % max(controls, 1)}", "m1", idx, b"blob"),
                )
        return path

    def test_definitions_include_expected_jobs_assets_and_sensor(self):
        # Verifies Dagster definitions wiring registers core parity assets/jobs/sensor.
        definitions = definitions_module.definitions
        self.assertIsNotNone(definitions.resolve_job_def("snapshot_job"))
        self.assertIsNotNone(definitions.resolve_job_def("testing_snapshot_job"))
        self.assertIsNotNone(definitions.resolve_job_def("testing_api_flow_job"))
        self.assertEqual(len(definitions.sensors), 1)
        self.assertEqual(len(definitions.schedules), 1)

    def test_schedule_timezone_prefers_reporting_override_then_runtime_timezone(self):
        # Verifies schedule timezone can be driven by environment settings.
        original_reporting_tz = os.environ.get("HAA_REPORTING_TIMEZONE")

        def _restore_reporting_tz() -> None:
            if original_reporting_tz is None:
                os.environ.pop("HAA_REPORTING_TIMEZONE", None)
            else:
                os.environ["HAA_REPORTING_TIMEZONE"] = original_reporting_tz

        self.addCleanup(lambda: importlib.reload(definitions_module))
        self.addCleanup(_restore_reporting_tz)
        with patch.dict(
            os.environ,
            {"HAA_REPORTING_TIMEZONE": "America/Chicago", "HAA_TIMEZONE": "UTC"},
            clear=False,
        ):
            reloaded = importlib.reload(definitions_module)
            self.assertEqual(reloaded.snapshot_schedule.execution_timezone, "America/Chicago")
        with patch.dict(
            os.environ,
            {"HAA_TIMEZONE": "Europe/Paris"},
            clear=False,
        ):
            os.environ.pop("HAA_REPORTING_TIMEZONE", None)
            reloaded = importlib.reload(definitions_module)
            self.assertEqual(reloaded.snapshot_schedule.execution_timezone, "Europe/Paris")

    def test_missing_snapshot_is_a_failure_not_a_success_materialization(self):
        """Missing snapshots should surface as a failure with actionable metadata."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "exception") as mock_exception:
                def _missing_path():
                    raise RuntimeError("no snapshot files found")

                with self.assertRaises(Failure) as cm:
                    assets._summarize_snapshot(context, _missing_path, "main")
        mock_exception.assert_called_once()
        self.assertEqual(cm.exception.metadata["snapshot_missing"].value, True)
        self.assertEqual(cm.exception.metadata["target"].value, "main")

    def test_snapshot_summary_reads_counts_from_real_snapshot(self):
        """Read a real sqlite file so summary metadata stays tied to actual schema names."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "info"):
                with tempfile.TemporaryDirectory() as tmp:
                    snapshot_path = self._write_snapshot(Path(tmp), "main.sqlite", controls=2, aggregates=3)
                    result = assets._summarize_snapshot(context, lambda: snapshot_path, "main")
        self.assertEqual(result.metadata["controls_count"], 2)
        self.assertEqual(result.metadata["aggregates_count"], 3)

    def test_testing_snapshot_summary_reads_counts_from_real_snapshot(self):
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "info"):
                with tempfile.TemporaryDirectory() as tmp:
                    snapshot_path = self._write_snapshot(Path(tmp), "testing.sqlite", controls=1, aggregates=1)
                    result = assets._summarize_snapshot(context, lambda: snapshot_path, "testing")
        self.assertEqual(result.metadata["controls_count"], 1)
        self.assertEqual(result.metadata["aggregates_count"], 1)

    def test_testing_api_flow_raises_failure_when_api_times_out(self):
        """Transport failures should look like missing external state, not silent skips."""
        timeout_error = urllib.error.URLError("timed out")
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "exception") as mock_exception:
                with patch("reporting_service.assets._post_json", side_effect=timeout_error):
                    with self.assertRaises(Failure) as cm:
                        assets.testing_api_snapshot_validation(context)
        mock_exception.assert_called_once()
        self.assertEqual(cm.exception.metadata["snapshot_missing"].value, True)

    def test_testing_api_flow_fails_on_bad_snapshot_export_status(self):
        """A bad export status should preserve the failing step in the Dagster error path."""
        with self._quiet_asset_context() as context:
        # Sequence maps to testing_api_snapshot_validation calls via reporting_service.assets._post_json:
        # reset -> create c1 -> create c2 -> holding c1 -> holding c2 -> snapshot export.
            with patch.object(context.log, "exception") as mock_exception:
                post_results = [
                    (200, {"status": "ok"}),
                    (202, {"status": "accepted"}),
                    (202, {"status": "accepted"}),
                    (202, {"status": "accepted"}),
                    (202, {"status": "accepted"}),
                    (500, {"error": "snapshot export failed"}),
                ]
                expected_post_calls = 6
                with patch("reporting_service.assets._post_json", side_effect=post_results) as mock_post:
                    with self.assertRaisesRegex(Failure, "snapshot export failed") as cm:
                        assets.testing_api_snapshot_validation(context)
        self.assertEqual(mock_post.call_count, expected_post_calls)
        mock_exception.assert_called_once()
        self.assertEqual(cm.exception.metadata["snapshot_missing"].value, True)

    def test_testing_api_flow_fails_on_escaped_snapshot_path(self):
        """Regression: a 200 response must still reject paths outside the allowed root."""
        with self._quiet_asset_context() as context:
            post_results = [
                (200, {"status": "ok"}),
                (202, {"status": "accepted"}),
                (202, {"status": "accepted"}),
                (202, {"status": "accepted"}),
                (202, {"status": "accepted"}),
                (200, {"snapshotPath": "../escape.sqlite"}),
            ]
            expected_post_calls = 6
            safe_root = Path("/tmp/asset-test-snapshots")
            with patch("reporting_service.assets._post_json", side_effect=post_results) as mock_post:
                with patch("reporting_service.assets._ensure_bootstrap"):
                    with patch(
                        "reporting_service.assets._test_snapshot_root_fn",
                        return_value=safe_root,
                    ):
                        with self.assertRaisesRegex(Failure, r"escapes") as cm:
                            assets.testing_api_snapshot_validation(context)
        self.assertEqual(mock_post.call_count, expected_post_calls)
        self.assertEqual(cm.exception.metadata["snapshot_missing"].value, True)
        self.assertEqual(cm.exception.metadata["snapshot_path"].value, "../escape.sqlite")

    def test_testing_api_flow_succeeds_with_valid_snapshot(self):
        """The mocked API flow still exercises the real sqlite validation logic."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "info"), patch.object(context.log, "exception"):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    snapshot_path = self._write_snapshot(
                        root,
                        "dagster-asset-flow-dagster-asset-flow-snapshot.sqlite",
                        controls=2,
                        aggregates=2,
                    )
                    post_results = [
                        (200, {"status": "ok"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (200, {"snapshotPath": snapshot_path.name}),
                    ]
                    with patch("reporting_service.assets._post_json", side_effect=post_results):
                        with patch("reporting_service.assets._ensure_bootstrap"):
                            with patch("reporting_service.assets._test_snapshot_root_fn", return_value=root):
                                with patch("reporting_service.assets._repository_root_fn", return_value=root):
                                    result = assets.testing_api_snapshot_validation(context)
        self.assertEqual(result.metadata["controls_count"], 2)
        self.assertEqual(result.metadata["aggregates_count"], 2)

    def test_testing_api_flow_fails_when_snapshot_file_missing_after_export(self):
        """A nominally successful export response is not enough if no file was written."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "exception"):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    post_results = [
                        (200, {"status": "ok"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (200, {"snapshotPath": "missing.sqlite"}),
                    ]
                    with patch("reporting_service.assets._post_json", side_effect=post_results):
                        with patch("reporting_service.assets._ensure_bootstrap"):
                            with patch("reporting_service.assets._test_snapshot_root_fn", return_value=root):
                                with self.assertRaisesRegex(Failure, "expected snapshot not found") as cm:
                                    assets.testing_api_snapshot_validation(context)
        self.assertEqual(cm.exception.metadata["snapshot_missing"].value, True)

    def test_testing_api_flow_fails_when_snapshot_is_corrupt(self):
        """Corrupt sqlite files should fail at read time with corruption metadata."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "exception"):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    snapshot_path = root / "dagster-asset-flow-dagster-asset-flow-snapshot.sqlite"
                    snapshot_path.write_text("not a sqlite db")
                    post_results = [
                        (200, {"status": "ok"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (200, {"snapshotPath": snapshot_path.name}),
                    ]
                    with patch("reporting_service.assets._post_json", side_effect=post_results):
                        with patch("reporting_service.assets._ensure_bootstrap"):
                            with patch("reporting_service.assets._test_snapshot_root_fn", return_value=root):
                                with self.assertRaisesRegex(Failure, "snapshot read failed") as cm:
                                    assets.testing_api_snapshot_validation(context)
        self.assertEqual(cm.exception.metadata["snapshot_corrupt"].value, True)

    def test_testing_api_flow_fails_when_snapshot_has_too_few_controls(self):
        """Protect against reporting false success on partial or truncated exports."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "exception"):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    snapshot_path = self._write_snapshot(
                        root,
                        "dagster-asset-flow-dagster-asset-flow-snapshot.sqlite",
                        controls=1,
                        aggregates=2,
                    )
                    post_results = [
                        (200, {"status": "ok"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (200, {"snapshotPath": snapshot_path.name}),
                    ]
                    with patch("reporting_service.assets._post_json", side_effect=post_results):
                        with patch("reporting_service.assets._ensure_bootstrap"):
                            with patch("reporting_service.assets._test_snapshot_root_fn", return_value=root):
                                with self.assertRaisesRegex(Failure, "at least 2 controls"):
                                    assets.testing_api_snapshot_validation(context)

    def test_testing_api_flow_fails_when_snapshot_has_too_few_aggregates(self):
        """Aggregate-count assertions prove the asset checked more than metadata rows alone."""
        with self._quiet_asset_context() as context:
            with patch.object(context.log, "exception"):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    snapshot_path = self._write_snapshot(
                        root,
                        "dagster-asset-flow-dagster-asset-flow-snapshot.sqlite",
                        controls=2,
                        aggregates=1,
                    )
                    post_results = [
                        (200, {"status": "ok"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (202, {"status": "accepted"}),
                        (200, {"snapshotPath": snapshot_path.name}),
                    ]
                    with patch("reporting_service.assets._post_json", side_effect=post_results):
                        with patch("reporting_service.assets._ensure_bootstrap"):
                            with patch("reporting_service.assets._test_snapshot_root_fn", return_value=root):
                                with self.assertRaisesRegex(Failure, "at least 2 aggregates"):
                                    assets.testing_api_snapshot_validation(context)

    def test_post_json_returns_error_payload_for_http_error_response(self):
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:8081/v1/snapshots",
            code=500,
            msg="boom",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"boom"}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            status, payload = assets._post_json("http://127.0.0.1:8081/v1/snapshots", {"a": 1})
        self.assertEqual(status, 500)
        self.assertEqual(payload, {"error": "boom"})

    def test_post_json_returns_sanitized_error_payload_for_empty_http_error_body(self):
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:8081/v1/snapshots",
            code=500,
            msg="boom",
            hdrs=None,
            fp=io.BytesIO(b""),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            status, payload = assets._post_json("http://127.0.0.1:8081/v1/snapshots", {"a": 1})
        self.assertEqual(status, 500)
        self.assertEqual(payload, {"error": ""})

    def test_post_json_returns_sanitized_error_payload_for_malformed_http_error_body(self):
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:8081/v1/snapshots",
            code=500,
            msg="boom",
            hdrs=None,
            fp=io.BytesIO(b"bad\npayload"),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            status, payload = assets._post_json("http://127.0.0.1:8081/v1/snapshots", {"a": 1})
        self.assertEqual(status, 500)
        self.assertEqual(payload, {"error": "bad payload"})

    def test_post_json_handles_non_dict_success_payload(self):
        response = io.BytesIO(b"[1,2,3]")
        response.status = 200
        response.__enter__ = lambda self=response: self
        response.__exit__ = lambda exc_type, exc, tb: False
        with patch("urllib.request.urlopen", return_value=response):
            status, payload = assets._post_json("http://127.0.0.1:8081/v1/snapshots", {"a": 1})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"error": "unexpected payload type: list"})

    def test_latest_snapshot_path_in_dir_selects_newest_sqlite_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "older.sqlite"
            newer = root / "newer.sqlite"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))
            self.assertEqual(assets._latest_snapshot_path_in_dir(root), newer)

    def test_snapshot_sensor_emits_run_request_for_new_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snapshot.sqlite"
            snapshot_path.write_bytes(b"x")

            class Context:
                cursor = None

                def __init__(self):
                    self.updated = None

                def update_cursor(self, value):
                    self.updated = value

            context = Context()
            with patch("reporting_service.assets._latest_snapshot_path", return_value=snapshot_path):
                result = assets.snapshot_sensor._raw_fn(context)
            self.assertEqual(result.run_key, f"snapshot-{snapshot_path.stat().st_mtime_ns}")
            self.assertEqual(context.updated, str(snapshot_path.stat().st_mtime_ns))

    def test_snapshot_sensor_skips_when_cursor_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snapshot.sqlite"
            snapshot_path.write_bytes(b"x")
            current = str(snapshot_path.stat().st_mtime_ns)

            class Context:
                cursor = current

                def update_cursor(self, value):
                    raise AssertionError("cursor should not update")

            with patch("reporting_service.assets._latest_snapshot_path", return_value=snapshot_path):
                result = assets.snapshot_sensor._raw_fn(Context())
            self.assertEqual(result.skip_message, "no new snapshot")

    def test_snapshot_sensor_skips_when_snapshot_removed(self):
        snapshot_path = Path("/tmp/missing-snapshot.sqlite")

        class Context:
            cursor = None

            def update_cursor(self, value):
                raise AssertionError("cursor should not update")

        with patch("reporting_service.assets._latest_snapshot_path", return_value=snapshot_path):
            result = assets.snapshot_sensor._raw_fn(Context())
        self.assertEqual(result.skip_message, "snapshot removed")

    def test_snapshot_sensor_tolerates_invalid_cursor_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snapshot.sqlite"
            snapshot_path.write_bytes(b"x")

            class Context:
                cursor = "not-a-number"

                def __init__(self):
                    self.updated = None

                def update_cursor(self, value):
                    self.updated = value

            context = Context()
            with patch("reporting_service.assets._latest_snapshot_path", return_value=snapshot_path):
                result = assets.snapshot_sensor._raw_fn(context)
            self.assertEqual(result.run_key, f"snapshot-{snapshot_path.stat().st_mtime_ns}")
            self.assertEqual(context.updated, str(snapshot_path.stat().st_mtime_ns))


if __name__ == "__main__":
    unittest.main()
