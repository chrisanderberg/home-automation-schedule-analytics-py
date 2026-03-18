"""API contract tests for the main and testing Flask surfaces.

These tests focus on request validation and the externally visible side-effects
that callers care about: accepted writes, rejected bad payloads, and snapshot
artifacts written to the expected place.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aggregation_service.app_factory import create_main_app, create_testing_app
from shared_logic.contracts import Config


class ApiTests(unittest.TestCase):
    """Exercise both app factories with isolated sqlite state per test."""

    def setUp(self):
        """Create one stable runtime config so failures point at API behavior."""
        self.cfg = Config(time_zone="UTC", latitude=37.77, longitude=-122.42)

    def _main_client(self):
        """Build a main-app client backed by a temporary production-style DB path."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        env = patch.dict(os.environ, {"HAA_DB_PATH": str(data_dir / "main.sqlite")}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        app = create_main_app(self.cfg)
        return app.test_client(), data_dir / "main.sqlite"

    def _testing_client(self):
        """Build a testing-app client with an isolated test-data root and snapshots dir."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        test_root = Path(tmp.name) / "test-data"
        test_root.mkdir(parents=True, exist_ok=True)
        (test_root / "snapshots").mkdir(parents=True, exist_ok=True)
        env = patch.dict(os.environ, {"TEST_DATA_DIR": str(test_root), "HAA_DB_PATH": ""}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        app = create_testing_app(self.cfg)
        return app.test_client(), test_root

    def test_main_control_and_holding(self):
        """Smoke-test the most common happy path: define a control, then ingest data."""
        client, _db_path = self._main_client()
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

    def test_main_transition_endpoint_accepts_valid_payload(self):
        """Transitions should work once the control metadata exists."""
        client, _db_path = self._main_client()
        client.post("/v1/controls", json={"controlId": "mode", "controlType": "discrete", "numStates": 2})
        response = client.post(
            "/v1/transitions",
            json={
                "controlId": "mode",
                "modelId": "m1",
                "fromState": 0,
                "toState": 1,
                "timestampMs": 1704067500000,
            },
        )
        self.assertEqual(response.status_code, 202)

    def test_main_snapshot_endpoint_exports_snapshot_file(self):
        """The API should export a snapshot artifact, not return the live DB path."""
        client, db_path = self._main_client()
        client.post("/v1/controls", json={"controlId": "mode", "controlType": "discrete", "numStates": 2})

        response = client.post("/v1/snapshots", json={})

        self.assertEqual(response.status_code, 200)
        snapshot_path = Path(response.get_json()["snapshotPath"])
        self.assertTrue(snapshot_path.exists())
        self.assertNotEqual(snapshot_path, db_path)

    def test_testing_snapshot_endpoint_exports_named_snapshot_file(self):
        """Reporting relies on the deterministic testing snapshot filename convention."""
        client, test_root = self._testing_client()
        client.post(
            "/v1/controls",
            json={"testName": "case-a", "controlId": "mode", "controlType": "discrete", "numStates": 2},
        )

        response = client.post("/v1/snapshots", json={"testName": "case-a", "snapshotName": "baseline"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["snapshotName"], "baseline")
        self.assertEqual(Path(payload["snapshotPath"]).name, "case-a-baseline-snapshot.sqlite")
        self.assertTrue((test_root / "snapshots" / "case-a-baseline-snapshot.sqlite").exists())

    def test_testing_reset_endpoint_removes_test_database(self):
        """Reset must be destructive so repeated validation runs start from a clean slate."""
        client, test_root = self._testing_client()
        create_response = client.post(
            "/v1/controls",
            json={"testName": "case-a", "controlId": "mode", "controlType": "discrete", "numStates": 2},
        )
        self.assertEqual(create_response.status_code, 202)
        self.assertTrue((test_root / "case-a-test-data.sqlite").exists())

        response = client.post("/v1/reset", json={"testName": "case-a"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse((test_root / "case-a-test-data.sqlite").exists())

    def test_main_controls_rejects_unknown_fields(self):
        """Unknown keys should fail fast so client/server contract drift is visible."""
        client, _db_path = self._main_client()
        response = client.post(
            "/v1/controls",
            json={"controlId": "mode", "controlType": "discrete", "numStates": 2, "extra": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid json", response.get_json()["error"])

    def test_main_controls_rejects_missing_required_fields(self):
        """Required fields should not be defaulted or ignored by the API layer."""
        client, _db_path = self._main_client()
        response = client.post("/v1/controls", json={"controlId": "mode", "controlType": "discrete"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid json", response.get_json()["error"])

    def test_main_controls_rejects_bool_for_num_states(self):
        """`bool` is a useful regression case because Python treats it as an `int` subclass."""
        client, _db_path = self._main_client()
        response = client.post(
            "/v1/controls",
            json={"controlId": "mode", "controlType": "discrete", "numStates": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid numStates", response.get_json()["error"])

    def test_main_controls_rejects_invalid_state_labels_length(self):
        """State labels must stay aligned with the configured number of states."""
        client, _db_path = self._main_client()
        response = client.post(
            "/v1/controls",
            json={
                "controlId": "mode",
                "controlType": "discrete",
                "numStates": 2,
                "stateLabels": ["off"],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("stateLabels length must equal numStates", response.get_json()["error"])

    def test_main_holding_rejects_unknown_control(self):
        """Ingest should not create implicit controls when metadata is missing."""
        client, _db_path = self._main_client()
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
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown control", response.get_json()["error"])

    def test_main_holding_rejects_invalid_json_body(self):
        """Malformed JSON should still map to the stable public error shape."""
        client, _db_path = self._main_client()
        response = client.post(
            "/v1/holding-intervals",
            data="{bad-json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid json")

    def test_main_holding_rejects_non_json_content_type(self):
        """The endpoint should reject bad content types before payload decoding."""
        client, _db_path = self._main_client()
        response = client.post("/v1/holding-intervals", data="controlId=mode", content_type="text/plain")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid json")

    def test_main_transition_rejects_self_transition(self):
        """Self-transitions are invalid domain events and should stay invalid at the API boundary."""
        client, _db_path = self._main_client()
        client.post("/v1/controls", json={"controlId": "mode", "controlType": "discrete", "numStates": 2})
        response = client.post(
            "/v1/transitions",
            json={
                "controlId": "mode",
                "modelId": "m1",
                "fromState": 1,
                "toState": 1,
                "timestampMs": 1704067500000,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("from_state must not equal to_state", response.get_json()["error"])

    def test_main_transition_rejects_bool_for_timestamp(self):
        """Timestamp validation needs the same bool-guard as other integer fields."""
        client, _db_path = self._main_client()
        client.post("/v1/controls", json={"controlId": "mode", "controlType": "discrete", "numStates": 2})
        response = client.post(
            "/v1/transitions",
            json={
                "controlId": "mode",
                "modelId": "m1",
                "fromState": 0,
                "toState": 1,
                "timestampMs": True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid timestampMs", response.get_json()["error"])

    def test_testing_endpoints_require_slug_test_name_consistently(self):
        """Every testing endpoint should enforce the same `testName` slug contract."""
        client, _test_root = self._testing_client()
        cases = [
            ("/v1/controls", {"testName": "Bad Name", "controlId": "mode", "controlType": "discrete", "numStates": 2}),
            (
                "/v1/holding-intervals",
                {
                    "testName": "Bad Name",
                    "controlId": "mode",
                    "modelId": "m1",
                    "state": 1,
                    "startTimeMs": 1704067200000,
                    "endTimeMs": 1704067260000,
                },
            ),
            (
                "/v1/transitions",
                {
                    "testName": "Bad Name",
                    "controlId": "mode",
                    "modelId": "m1",
                    "fromState": 0,
                    "toState": 1,
                    "timestampMs": 1704067500000,
                },
            ),
            ("/v1/snapshots", {"testName": "Bad Name", "snapshotName": "baseline"}),
            ("/v1/reset", {"testName": "Bad Name"}),
        ]
        for path, payload in cases:
            with self.subTest(path=path):
                response = client.post(path, json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("invalid testName", response.get_json()["error"])

    def test_testing_flow_reset_create_ingest_snapshot_produces_expected_sqlite_contents(self):
        """Mirror the light end-to-end testing flow that reporting depends on downstream."""
        client, _test_root = self._testing_client()
        client.post("/v1/reset", json={"testName": "case-a"})
        client.post(
            "/v1/controls",
            json={"testName": "case-a", "controlId": "mode", "controlType": "discrete", "numStates": 2},
        )
        client.post(
            "/v1/holding-intervals",
            json={
                "testName": "case-a",
                "controlId": "mode",
                "modelId": "m1",
                "state": 1,
                "startTimeMs": 1704067200000,
                "endTimeMs": 1704067260000,
            },
        )
        response = client.post("/v1/snapshots", json={"testName": "case-a", "snapshotName": "baseline"})

        self.assertEqual(response.status_code, 200)
        snapshot_path = Path(response.get_json()["snapshotPath"])
        with sqlite3.connect(str(snapshot_path)) as conn:
            controls_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
            aggregates_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]
        self.assertEqual(controls_count, 1)
        self.assertEqual(aggregates_count, 1)


if __name__ == "__main__":
    unittest.main()
