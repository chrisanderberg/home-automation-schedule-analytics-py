"""Dagster definition/asset smoke tests."""

from __future__ import annotations

import importlib
import importlib.util
import os
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
        # Verifies missing snapshot paths fail the asset run with explicit metadata.
        context = build_asset_context()

        def _missing_path():
            raise RuntimeError("no snapshot files found")

        with self.assertRaises(Failure):
            assets._summarize_snapshot(context, _missing_path, "main")

    def test_testing_api_flow_raises_failure_when_api_times_out(self):
        # Verifies transport-level outages are surfaced as Dagster failures.
        context = build_asset_context()
        timeout_error = urllib.error.URLError("timed out")
        with patch("reporting_service.assets._post_json", side_effect=timeout_error):
            with self.assertRaises(Failure):
                assets.testing_api_snapshot_validation(context)

    def test_testing_api_flow_fails_on_bad_snapshot_export_status(self):
        # Verifies non-200 snapshot export responses fail fast with step context.
        context = build_asset_context()
        # Sequence maps to testing_api_snapshot_validation calls via reporting_service.assets._post_json:
        # reset -> create c1 -> create c2 -> holding c1 -> holding c2 -> snapshot export.
        post_results = [
            (200, {"status": "ok"}),  # reset
            (202, {"status": "accepted"}),  # c1
            (202, {"status": "accepted"}),  # c2
            (202, {"status": "accepted"}),  # holding c1
            (202, {"status": "accepted"}),  # holding c2
            (500, {"error": "snapshot export failed"}),  # snapshot export
        ]
        expected_post_calls = 6
        with patch("reporting_service.assets._post_json", side_effect=post_results) as mock_post:
            with self.assertRaisesRegex(Failure, "snapshot export failed"):
                assets.testing_api_snapshot_validation(context)
        self.assertEqual(mock_post.call_count, expected_post_calls)

    def test_testing_api_flow_fails_on_escaped_snapshot_path(self):
        # Regression: snapshot export returning 200 with escaped snapshotPath is rejected.
        # Patch bootstrap/snapshot root so flow stops at escape check without importing shared_logic.
        context = build_asset_context()
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
                    with self.assertRaisesRegex(Failure, r"escapes"):
                        assets.testing_api_snapshot_validation(context)
        self.assertEqual(mock_post.call_count, expected_post_calls)


if __name__ == "__main__":
    unittest.main()
