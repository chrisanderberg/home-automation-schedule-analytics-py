"""Live integration test for the reporting validation asset against the testing API."""

from __future__ import annotations

from contextlib import ExitStack
import os
import tempfile
import time
import unittest
import unittest.mock as mock
import urllib.request
from pathlib import Path

from dagster import build_asset_context

from aggregation_service.main import PortBindError, ServerController
from reporting_service import assets
from shared_logic.contracts import Config


class ReportingAssetIntegrationTests(unittest.TestCase):
    """Run the reporting asset against a real local testing server when binds are allowed."""

    def _wait_until_ready(self, url: str) -> None:
        """Poll the testing API until the background server starts accepting traffic."""
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    if resp.status == 200:
                        return
            except Exception:  # pragma: no cover - only exercised on slow startup
                time.sleep(0.05)
        raise AssertionError(f"server did not become ready: {url}")

    def _start_controller_or_skip(self, cfg: Config) -> ServerController:
        """Skip cleanly when the environment blocks local port binding."""
        try:
            controller = ServerController(cfg, main_port=0, testing_port=0)
        except (OSError, PortBindError, SystemExit) as exc:
            raise unittest.SkipTest(f"socket bind not permitted in this environment: {exc}") from exc
        self.addCleanup(controller.stop)
        controller.start()
        return controller

    def test_testing_api_snapshot_can_be_consumed_by_reporting_asset_flow(self):
        """Exercise the exact cross-service flow the validation asset is meant to prove."""
        cfg = Config(time_zone="UTC", latitude=37.77, longitude=-122.42)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_root = root / "test-data"
            test_root.mkdir()
            (test_root / "snapshots").mkdir()
            env = {
                "HAA_DB_PATH": str(root / "main.sqlite"),
                "TEST_DATA_DIR": str(test_root),
                "HAA_DAGSTER_TEST_NAME": "live-flow",
                "HAA_DAGSTER_SNAPSHOT_NAME": "integration",
            }
            previous = {key: os.environ.get(key) for key in env}
            os.environ.update(env)
            try:
                controller = self._start_controller_or_skip(cfg)
                testing_url = f"http://127.0.0.1:{controller.testing_server.server_port}"
                self._wait_until_ready(f"{testing_url}/v1/health")

                with ExitStack() as stack:
                    stack.enter_context(mock.patch.dict(os.environ, {"HAA_TESTING_API_URL": testing_url}, clear=False))
                    stack.enter_context(mock.patch("reporting_service.assets._ensure_bootstrap"))
                    stack.enter_context(
                        mock.patch("reporting_service.assets._test_snapshot_root_fn", return_value=test_root / "snapshots")
                    )
                    stack.enter_context(mock.patch("reporting_service.assets._repository_root_fn", return_value=root))
                    result = assets.testing_api_snapshot_validation(build_asset_context())
                self.assertEqual(result.metadata["controls_count"], 2)
                self.assertEqual(result.metadata["aggregates_count"], 2)
                self.assertEqual(result.metadata["test_name"], "live-flow")
                self.assertEqual(result.metadata["snapshot_name"], "integration")
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
