"""Aggregation API contract tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aggregation_service.app_factory import create_main_app, create_testing_app
from shared_logic.contracts import Config


class ApiTests(unittest.TestCase):
    def setUp(self):
        # Shared runtime clock config used by both main/testing Flask app factories.
        self.cfg = Config(time_zone="UTC", latitude=37.77, longitude=-122.42)

    def test_main_control_and_holding(self):
        # Verifies main API accepts valid control upsert and holding ingestion payloads.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            with patch.dict(os.environ, {"HAA_DB_PATH": str(data_dir / "main.sqlite")}, clear=False):
                app = create_main_app(self.cfg)
                client = app.test_client()

                r = client.post("/v1/controls", json={"controlId": "mode", "controlType": "discrete", "numStates": 2})
                self.assertEqual(r.status_code, 202)

                r = client.post(
                    "/v1/holding-intervals",
                    json={
                        "controlId": "mode",
                        "modelId": "m1",
                        "state": 1,
                        "startTimeMs": 1704067200000,
                        "endTimeMs": 1704067260000,
                    },
                )
                self.assertEqual(r.status_code, 202)

    def test_testing_requires_test_name_slug(self):
        # Verifies testing API rejects non-slug testName values.
        with patch.dict(os.environ, {"HAA_DB_PATH": ""}, clear=False):
            app = create_testing_app(self.cfg)
            client = app.test_client()
            r = client.post(
                "/v1/controls",
                json={"testName": "Bad Name", "controlId": "mode", "controlType": "discrete", "numStates": 2},
            )
            self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
