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
    Failure,
    MetadataValue,
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
    """Return the newest `.sqlite` snapshot file from a directory.

    Args:
        root: Snapshot directory to scan.

    Returns:
        Path to the most recently modified snapshot file.
    """
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"snapshot directory is not present: {root}")
    candidates = list(root.glob("*.sqlite"))
    if not candidates:
        raise RuntimeError(f"no snapshot files found in {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _latest_snapshot_path() -> Path:
    """Resolve the newest production snapshot path.

    Returns:
        Path to the newest production snapshot file.
    """
    return _latest_snapshot_path_in_dir(snapshot_root())


def _latest_testing_snapshot_path() -> Path:
    """Resolve the newest testing snapshot path.

    Returns:
        Path to the newest testing snapshot file.
    """
    return _latest_snapshot_path_in_dir(test_snapshot_root())


def _testing_api_base_url() -> str:
    """Read testing API base URL from environment with default.

    Args:
        None.

    Returns:
        Base URL string without trailing slash.
    """
    return os.getenv("HAA_TESTING_API_URL", "http://127.0.0.1:8081").rstrip("/")


def _testing_flow_test_name() -> str:
    """Read the configured test name for Dagster validation flow.

    Args:
        None.

    Returns:
        Test name slug string.
    """
    return os.getenv("HAA_DAGSTER_TEST_NAME", "dagster-asset-flow")


def _testing_flow_snapshot_name() -> str:
    """Read the configured snapshot name for Dagster validation flow.

    Args:
        None.

    Returns:
        Snapshot name slug string.
    """
    return os.getenv("HAA_DAGSTER_SNAPSHOT_NAME", "dagster-asset-flow")


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    """POST JSON and parse the response payload.

    Args:
        url: Endpoint URL to call.
        payload: JSON-compatible dictionary request payload.

    Returns:
        Tuple of HTTP status code and parsed response dictionary.
    """
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
    """Raise when an HTTP step does not return the expected status.

    Args:
        status: Actual response status code.
        expected: Required status code for the step.
        step: Human-readable step label.
        payload: Response payload used in the error message.

    Returns:
        None.
    """
    if status != expected:
        raise RuntimeError(f"{step} failed: expected {expected}, got {status}, payload={payload}")


def _summarize_snapshot(context: AssetExecutionContext, snapshot_path_fn, label: str) -> MaterializeResult:
    """Read snapshot table counts and return Dagster metadata.

    Args:
        context: Dagster asset execution context for logging.
        snapshot_path_fn: Callable that returns the target snapshot path.
        label: Label used in logs and metadata context.

    Returns:
        `MaterializeResult` with path and row-count metadata.
    """
    try:
        snapshot_path = snapshot_path_fn()
    except RuntimeError as exc:
        context.log.exception("snapshot lookup failed for %s: %s", label, exc)
        raise Failure(
            description=f"snapshot lookup failed for {label}: {exc}",
            metadata={"snapshot_missing": True, "target": label},
        ) from exc

    context.log.info("using %s snapshot %s", label, snapshot_path)

    with closing(sqlite3.connect(str(snapshot_path))) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM controls")
        controls_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM aggregates")
        aggregates_count = cur.fetchone()[0]

    return MaterializeResult(
        metadata={
            "snapshot_path": MetadataValue.path(snapshot_path),
            "controls_count": controls_count,
            "aggregates_count": aggregates_count,
        }
    )


@asset
def snapshot_summary(context: AssetExecutionContext) -> MaterializeResult:
    """Materialize metadata summary for the latest production snapshot.

    Args:
        context: Dagster asset execution context.

    Returns:
        `MaterializeResult` describing the latest production snapshot.
    """
    return _summarize_snapshot(context, _latest_snapshot_path, "main")


@asset
def testing_snapshot_summary(context: AssetExecutionContext) -> MaterializeResult:
    """Materialize metadata summary for the latest testing snapshot.

    Args:
        context: Dagster asset execution context.

    Returns:
        `MaterializeResult` describing the latest testing snapshot.
    """
    return _summarize_snapshot(context, _latest_testing_snapshot_path, "testing")


@asset
def testing_api_snapshot_validation(context: AssetExecutionContext) -> MaterializeResult:
    """Exercise testing API flow and validate exported snapshot contents.

    Args:
        context: Dagster asset execution context.

    Returns:
        `MaterializeResult` with validation metadata for the test snapshot.
    """
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
        context.log.exception(message)
        raise Failure(description=message, metadata={"snapshot_missing": True}) from exc
    except RuntimeError as exc:
        message = (
            "testing API validation failed"
            f" (base_url={base_url}, test_name={test_name}, snapshot_name={snapshot_name}): {exc}"
        )
        context.log.exception(message)
        raise Failure(description=message, metadata={"snapshot_missing": True}) from exc

    snapshot_path_raw = None
    for key in ("snapshotPath", "snapshot_path", "path", "filename"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            snapshot_path_raw = value
            break
    if snapshot_path_raw is not None:
        root = test_snapshot_root().resolve()
        candidate = (root / Path(snapshot_path_raw)).resolve()
        if not candidate.is_relative_to(root):
            raise Failure(
                description=f"snapshot path escapes test snapshot root: {snapshot_path_raw}",
                metadata={"snapshot_missing": True, "snapshot_path": snapshot_path_raw},
            )
        snapshot_path = candidate
    else:
        snapshot_path = test_snapshot_root() / f"{test_name}-{snapshot_name}-snapshot.sqlite"
    if not snapshot_path.exists():
        raise Failure(
            description=f"expected snapshot not found after export: {snapshot_path}",
            metadata={"snapshot_missing": True, "snapshot_path": MetadataValue.path(snapshot_path)},
        )

    with closing(sqlite3.connect(str(snapshot_path))) as conn:
        controls_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        aggregates_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]

    if controls_count < 2:
        raise Failure(
            description=f"snapshot should contain at least 2 controls, got {controls_count}",
            metadata={"snapshot_path": MetadataValue.path(snapshot_path), "controls_count": controls_count},
        )
    if aggregates_count < 2:
        raise Failure(
            description=f"snapshot should contain at least 2 aggregates, got {aggregates_count}",
            metadata={"snapshot_path": MetadataValue.path(snapshot_path), "aggregates_count": aggregates_count},
        )

    return MaterializeResult(
        metadata={
            "repository_root": MetadataValue.path(repository_root()),
            "testing_api_url": base_url,
            "snapshot_path": MetadataValue.path(snapshot_path),
            "controls_count": controls_count,
            "aggregates_count": aggregates_count,
            "test_name": test_name,
            "snapshot_name": snapshot_name,
        }
    )


@sensor(job_name="snapshot_job")
def snapshot_sensor(context: SensorEvaluationContext):
    """Trigger snapshot job when a newer production snapshot appears.

    Args:
        context: Dagster sensor evaluation context and cursor holder.

    Returns:
        `RunRequest` when new data exists, otherwise `SkipReason`.
    """
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
