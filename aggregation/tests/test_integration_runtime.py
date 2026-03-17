"""Live HTTP tests for the dual-port development runtime."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from urllib.error import URLError

from aggregation_service.main import ServerController
from shared_logic.contracts import Config


class RuntimeIntegrationTests(unittest.TestCase):
    """Exercise real socket binding, health checks, and sqlite artifacts."""

    def setUp(self):
        """Use one stable config so failures point at runtime wiring, not clock math."""
        self.cfg = Config(time_zone="UTC", latitude=37.77, longitude=-122.42)

    def _fetch_json(self, url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
        """Issue a small JSON request against the live local server."""
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _start_controller_or_skip(self) -> ServerController:
        """Skip cleanly when the environment blocks local socket binds."""
        try:
            controller = ServerController(self.cfg, main_port=0, testing_port=0)
        except SystemExit as exc:
            raise unittest.SkipTest(f"socket bind not permitted in this environment: {exc}") from exc
        self.addCleanup(controller.stop)
        controller.start()
        return controller

    def _wait_until_ready(self, url: str) -> None:
        """Poll a health endpoint until the background server accepts traffic."""
        deadline = time.time() + 5
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                status, _payload = self._fetch_json(url)
                if status == 200:
                    return
            except Exception as exc:  # pragma: no cover - only exercised on slow startup
                last_error = exc
                time.sleep(0.05)
        raise AssertionError(f"server did not become ready: {url} last_error={last_error!r}")

    def test_dual_server_runtime_serves_main_and_testing_health_endpoints(self):
        """Both ports matter because local development relies on the split topology."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_root = root / "test-data"
            test_root.mkdir()
            (test_root / "snapshots").mkdir()
            env = {
                "HAA_DB_PATH": str(root / "main.sqlite"),
                "TEST_DATA_DIR": str(test_root),
            }
            previous = {key: os.environ.get(key) for key in env}
            os.environ.update(env)
            try:
                controller = self._start_controller_or_skip()
                main_url = f"http://127.0.0.1:{controller.main_server.server_port}/v1/health"
                testing_url = f"http://127.0.0.1:{controller.testing_server.server_port}/v1/health"
                self._wait_until_ready(main_url)
                self._wait_until_ready(testing_url)

                main_status, main_payload = self._fetch_json(main_url)
                testing_status, testing_payload = self._fetch_json(testing_url)
                self.assertEqual(main_status, 200)
                self.assertEqual(testing_status, 200)
                self.assertEqual(main_payload, {"status": "ok"})
                self.assertEqual(testing_payload, {"status": "ok"})
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_testing_runtime_flow_exports_snapshot_with_expected_contents(self):
        """Run the testing flow over HTTP and inspect the exported sqlite snapshot directly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_root = root / "test-data"
            test_root.mkdir()
            (test_root / "snapshots").mkdir()
            env = {
                "HAA_DB_PATH": str(root / "main.sqlite"),
                "TEST_DATA_DIR": str(test_root),
            }
            previous = {key: os.environ.get(key) for key in env}
            os.environ.update(env)
            try:
                controller = self._start_controller_or_skip()
                base_url = f"http://127.0.0.1:{controller.testing_server.server_port}"
                self._wait_until_ready(f"{base_url}/v1/health")

                # Reset first so this test proves the expected clean-start behavior.
                status, _ = self._fetch_json(f"{base_url}/v1/reset", method="POST", payload={"testName": "case-a"})
                self.assertEqual(status, 200)
                status, _ = self._fetch_json(
                    f"{base_url}/v1/controls",
                    method="POST",
                    payload={
                        "testName": "case-a",
                        "controlId": "mode",
                        "controlType": "discrete",
                        "numStates": 2,
                    },
                )
                self.assertEqual(status, 202)
                status, _ = self._fetch_json(
                    f"{base_url}/v1/holding-intervals",
                    method="POST",
                    payload={
                        "testName": "case-a",
                        "controlId": "mode",
                        "modelId": "m1",
                        "state": 1,
                        "startTimeMs": 1704067200000,
                        "endTimeMs": 1704067260000,
                    },
                )
                self.assertEqual(status, 202)
                status, payload = self._fetch_json(
                    f"{base_url}/v1/snapshots",
                    method="POST",
                    payload={"testName": "case-a", "snapshotName": "baseline"},
                )
                self.assertEqual(status, 200)

                snapshot_path = Path(payload["snapshotPath"])
                self.assertTrue(snapshot_path.exists())
                with sqlite3.connect(str(snapshot_path)) as conn:
                    controls_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
                    aggregates_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]
                self.assertEqual(controls_count, 1)
                self.assertEqual(aggregates_count, 1)
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
