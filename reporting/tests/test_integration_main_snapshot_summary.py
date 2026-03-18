"""Integration test for main-API snapshot export consumed by reporting summary logic."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dagster import build_asset_context

from aggregation_service.app_factory import create_main_app
from reporting_service import assets
from shared_logic.contracts import Config


class MainSnapshotSummaryIntegrationTests(unittest.TestCase):
    def test_main_api_snapshot_can_be_summarized_by_reporting_asset(self):
        """Connect the main API export path to the reporting summary reader end to end."""
        cfg = Config(time_zone="UTC", latitude=37.77, longitude=-122.42)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_dir = root / "snapshots"
            db_path = root / "main.sqlite"
            previous_db_path = os.environ.get("HAA_DB_PATH")
            os.environ["HAA_DB_PATH"] = str(db_path)
            try:
                app = create_main_app(cfg)
                client = app.test_client()
                response = client.post(
                    "/v1/controls",
                    json={"controlId": "mode", "controlType": "discrete", "numStates": 2},
                )
                self.assertEqual(response.status_code, 202)
                response = client.post(
                    "/v1/holding-intervals",
                    json={
                        "controlId": "mode",
                        "modelId": "m1",
                        "state": 1,
                        "startTimeMs": 1704067200000,
                        "endTimeMs": 1704067260000,
                    },
                )
                self.assertEqual(response.status_code, 202)
                # Patch only the snapshot root so this stays isolated from repo data/.
                with patch("shared_logic.snapshot.snapshot_root", return_value=snapshots_dir):
                    response = client.post("/v1/snapshots", json={})
                self.assertEqual(response.status_code, 200)

                with patch("reporting_service.assets._ensure_bootstrap"):
                    with patch("reporting_service.assets._snapshot_root_fn", return_value=snapshots_dir):
                        result = assets.snapshot_summary(build_asset_context())
                self.assertEqual(result.metadata["controls_count"], 1)
                self.assertEqual(result.metadata["aggregates_count"], 1)
            finally:
                if previous_db_path is None:
                    os.environ.pop("HAA_DB_PATH", None)
                else:
                    os.environ["HAA_DB_PATH"] = previous_db_path


if __name__ == "__main__":
    unittest.main()
