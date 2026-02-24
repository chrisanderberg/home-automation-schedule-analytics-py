"""Dagster assets and sensors for snapshot validation and reporting."""

import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    asset,
    sensor,
)

from reporting_service.bootstrap import ensure_repo_src_paths
from reporting_service.http_json import decode_json_body

ensure_repo_src_paths()

from shared_logic.paths import repository_root, snapshot_root, test_snapshot_root  # noqa: E402


def _latest_snapshot_path_in_dir(root: Path) -> Path:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"snapshot directory is not present: {root}")
    candidates = list(root.glob("*.sqlite"))
    if not candidates:
        raise RuntimeError(f"no snapshot files found in {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _latest_snapshot_path() -> Path:
    return _latest_snapshot_path_in_dir(snapshot_root())


def _latest_testing_snapshot_path() -> Path:
    return _latest_snapshot_path_in_dir(test_snapshot_root())


def _testing_api_base_url() -> str:
    return os.getenv("HAA_TESTING_API_URL", "http://127.0.0.1:8081").rstrip("/")


def _testing_flow_test_name() -> str:
    return os.getenv("HAA_DAGSTER_TEST_NAME", "dagster-asset-flow")


def _testing_flow_snapshot_name() -> str:
    return os.getenv("HAA_DAGSTER_SNAPSHOT_NAME", "dagster-asset-flow")


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            try:
                parsed_any = decode_json_body(body, decode_error_as_error_payload=False)
            except ValueError:
                parsed_any = {}
            parsed = parsed_any if isinstance(parsed_any, dict) else {"error": f"unexpected payload type: {type(parsed_any).__name__}"}
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp is not None else ""
        parsed_any = decode_json_body(body, decode_error_as_error_payload=True)
        parsed = parsed_any if isinstance(parsed_any, dict) else {"error": f"unexpected payload type: {type(parsed_any).__name__}"}
        return exc.code, parsed


def _require_status(status: int, expected: int, step: str, payload: dict) -> None:
    if status != expected:
        raise RuntimeError(f"{step} failed: expected {expected}, got {status}, payload={payload}")


def _summarize_snapshot(context: AssetExecutionContext, snapshot_path_fn, label: str) -> MaterializeResult:
    try:
        snapshot_path = snapshot_path_fn()
    except RuntimeError as exc:
        context.log.warning("snapshot lookup failed for %s: %s", label, exc)
        return MaterializeResult(metadata={"snapshot_missing": True})

    context.log.info("using %s snapshot %s", label, snapshot_path)

    with closing(sqlite3.connect(str(snapshot_path))) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM controls")
        controls_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM aggregates")
        aggregates_count = cur.fetchone()[0]

    return MaterializeResult(
        metadata={
            "snapshot_path": str(snapshot_path),
            "controls_count": controls_count,
            "aggregates_count": aggregates_count,
        }
    )


@asset
def snapshot_summary(context: AssetExecutionContext) -> MaterializeResult:
    return _summarize_snapshot(context, _latest_snapshot_path, "main")


@asset
def testing_snapshot_summary(context: AssetExecutionContext) -> MaterializeResult:
    return _summarize_snapshot(context, _latest_testing_snapshot_path, "testing")


@asset
def testing_api_snapshot_validation(context: AssetExecutionContext) -> MaterializeResult:
    base_url = _testing_api_base_url()
    test_name = _testing_flow_test_name()
    snapshot_name = _testing_flow_snapshot_name()

    try:
        status, payload = _post_json(f"{base_url}/v1/reset", {"testName": test_name})
        _require_status(status, 200, "reset", payload)

        for control_id in ("c1", "c2"):
            status, payload = _post_json(
                f"{base_url}/v1/controls",
                {"testName": test_name, "controlId": control_id, "controlType": "discrete", "numStates": 2},
            )
            _require_status(status, 202, f"create control {control_id}", payload)

        status, payload = _post_json(
            f"{base_url}/v1/holding-intervals",
            {
                "testName": test_name,
                "controlId": "c1",
                "modelId": "m1",
                "state": 1,
                "startTimeMs": 1578268800000,
                "endTimeMs": 1578269100000,
            },
        )
        _require_status(status, 202, "holding c1", payload)

        status, payload = _post_json(
            f"{base_url}/v1/holding-intervals",
            {
                "testName": test_name,
                "controlId": "c2",
                "modelId": "m1",
                "state": 0,
                "startTimeMs": 1578269100000,
                "endTimeMs": 1578269400000,
            },
        )
        _require_status(status, 202, "holding c2", payload)

        status, payload = _post_json(
            f"{base_url}/v1/snapshots",
            {"testName": test_name, "snapshotName": snapshot_name},
        )
        _require_status(status, 200, "snapshot export", payload)
    except urllib.error.URLError as exc:
        message = f"testing API unavailable at {base_url}: {exc}"
        context.log.warning(message)
        return MaterializeResult(metadata={"snapshot_missing": True, "error": message})

    snapshot_path = test_snapshot_root() / f"{test_name}-{snapshot_name}-snapshot.sqlite"
    if not snapshot_path.exists():
        raise RuntimeError(f"expected snapshot not found after export: {snapshot_path}")

    with closing(sqlite3.connect(str(snapshot_path))) as conn:
        controls_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        aggregates_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]

    if controls_count < 2:
        raise RuntimeError(f"snapshot should contain at least 2 controls, got {controls_count}")
    if aggregates_count < 2:
        raise RuntimeError(f"snapshot should contain at least 2 aggregates, got {aggregates_count}")

    return MaterializeResult(
        metadata={
            "repository_root": str(repository_root()),
            "testing_api_url": base_url,
            "snapshot_path": str(snapshot_path),
            "controls_count": controls_count,
            "aggregates_count": aggregates_count,
            "test_name": test_name,
            "snapshot_name": snapshot_name,
        }
    )


@sensor(job_name="snapshot_job")
def snapshot_sensor(context: SensorEvaluationContext):
    try:
        snapshot_path = _latest_snapshot_path()
    except RuntimeError as exc:
        return SkipReason(str(exc))

    mtime_ns = snapshot_path.stat().st_mtime_ns
    try:
        last_seen = int(context.cursor) if context.cursor else -1
    except ValueError:
        last_seen = -1
    if mtime_ns <= last_seen:
        return SkipReason("no new snapshot")

    context.update_cursor(str(mtime_ns))
    return RunRequest(run_key=f"snapshot-{mtime_ns}", tags={"snapshot_path": str(snapshot_path)})
