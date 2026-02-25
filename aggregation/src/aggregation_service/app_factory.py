"""Flask application factories for main and testing APIs."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, request

from aggregation_service.jsonio import BadRequestError, decode_strict_json

from shared_logic.contracts import Config, Control, HoldingInput, TransitionInput
from shared_logic.errors import ValidationError
from shared_logic.ingest import ingest_holding, ingest_transition
from shared_logic.paths import data_root, test_data_root
from shared_logic.slug import is_valid_slug
from shared_logic.snapshot import export_snapshot, export_snapshot_for_test, reset_test_db_files
from shared_logic.storage import init_schema, open_db, upsert_control

_initialized_test_dbs: set[str] = set()
_initialized_test_dbs_lock = threading.Lock()
_test_db_init_locks: dict[str, threading.Lock] = {}
_test_db_init_locks_guard = threading.Lock()


def _is_int_not_bool(value: Any) -> bool:
    """Return True only for plain int, not bool or int subclasses."""
    return type(value) is int


def _test_db_init_lock(test_name: str) -> threading.Lock:
    """Return a lock dedicated to one test DB initialization key."""
    with _test_db_init_locks_guard:
        lock = _test_db_init_locks.get(test_name)
        if lock is None:
            lock = threading.Lock()
            _test_db_init_locks[test_name] = lock
        return lock


def _validate_control_payload(data: dict[str, Any], *, require_test_name: bool) -> tuple[Control, str | None]:
    """Validate a control payload and build a `Control`.

    Args:
        data: Request JSON payload for control creation/upsert.
        require_test_name: Whether `testName` must be present and valid.

    Returns:
        Tuple of validated `Control` and optional `testName`.
    """
    test_name = data.get("testName") if require_test_name else None
    control_id = data.get("controlId", "")
    control_type = data.get("controlType", "")
    num_states = data.get("numStates")
    state_labels = data.get("stateLabels")

    if require_test_name and (not isinstance(test_name, str) or not is_valid_slug(test_name)):
        raise ValidationError("invalid testName", field="testName")
    if not isinstance(control_id, str) or not control_id:
        raise ValidationError("invalid controlId")
    if control_type not in ("discrete", "slider"):
        raise ValidationError("invalid controlType")
    if not _is_int_not_bool(num_states) or num_states < 2 or num_states > 10:
        raise ValidationError("invalid numStates")
    if state_labels is not None:
        if not isinstance(state_labels, list) or not all(isinstance(x, str) for x in state_labels):
            raise ValidationError("invalid stateLabels")
        if len(state_labels) != num_states:
            raise ValidationError("stateLabels length must equal numStates")

    labels_tuple = tuple(state_labels) if state_labels is not None else None
    return (
        Control(
            control_id=control_id,
            control_type=control_type,
            num_states=num_states,
            state_labels=labels_tuple,
        ),
        test_name,
    )


def _validate_holding_payload(data: dict[str, Any], *, require_test_name: bool) -> tuple[HoldingInput, str | None]:
    """Validate a holding payload and build `HoldingInput`.

    Args:
        data: Request JSON payload for a holding interval.
        require_test_name: Whether `testName` must be present and valid.

    Returns:
        Tuple of validated `HoldingInput` and optional `testName`.
    """
    test_name = data.get("testName") if require_test_name else None
    if require_test_name and (not isinstance(test_name, str) or not is_valid_slug(test_name)):
        raise ValidationError("invalid testName", field="testName")

    control_id = data.get("controlId")
    model_id = data.get("modelId")
    state = data.get("state")
    start_time_ms = data.get("startTimeMs")
    end_time_ms = data.get("endTimeMs")
    if not isinstance(control_id, str) or not control_id:
        raise ValidationError("invalid controlId")
    if not isinstance(model_id, str) or not model_id:
        raise ValidationError("invalid modelId")
    if not _is_int_not_bool(state):
        raise ValidationError("invalid state")
    if not _is_int_not_bool(start_time_ms):
        raise ValidationError("invalid startTimeMs")
    if not _is_int_not_bool(end_time_ms):
        raise ValidationError("invalid endTimeMs")

    try:
        input_data = HoldingInput(
            control_id=control_id,
            model_id=model_id,
            state=state,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return input_data, test_name


def _validate_transition_payload(data: dict[str, Any], *, require_test_name: bool) -> tuple[TransitionInput, str | None]:
    """Validate a transition payload and build `TransitionInput`.

    Args:
        data: Request JSON payload for a transition event.
        require_test_name: Whether `testName` must be present and valid.

    Returns:
        Tuple of validated `TransitionInput` and optional `testName`.
    """
    test_name = data.get("testName") if require_test_name else None
    if require_test_name and (not isinstance(test_name, str) or not is_valid_slug(test_name)):
        raise ValidationError("invalid testName", field="testName")

    control_id = data.get("controlId")
    model_id = data.get("modelId")
    from_state = data.get("fromState")
    to_state = data.get("toState")
    timestamp_ms = data.get("timestampMs")
    if not isinstance(control_id, str) or not control_id:
        raise ValidationError("invalid controlId")
    if not isinstance(model_id, str) or not model_id:
        raise ValidationError("invalid modelId")
    if not _is_int_not_bool(from_state):
        raise ValidationError("invalid fromState")
    if not _is_int_not_bool(to_state):
        raise ValidationError("invalid toState")
    if not _is_int_not_bool(timestamp_ms):
        raise ValidationError("invalid timestampMs")

    try:
        input_data = TransitionInput(
            control_id=control_id,
            model_id=model_id,
            from_state=from_state,
            to_state=to_state,
            timestamp_ms=timestamp_ms,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return input_data, test_name


def _main_db_path() -> Path:
    """Resolve the production database path.

    Args:
        None.

    Returns:
        Absolute path to the main SQLite database.
    """
    override = os.getenv("HAA_DB_PATH", "").strip()
    if override:
        return Path(override).resolve()
    return data_root() / "data.sqlite"


def _open_main_db():
    """Open a connection to the production database.

    Args:
        None.

    Returns:
        Open SQLite connection to the main database path.
    """
    db_path = _main_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return open_db(db_path)


def _open_test_db_locked(test_name: str):
    """Open and initialize a per-test database while holding the per-test lock."""
    db_path = _test_db_path(test_name)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _initialized_test_dbs_lock:
        initialized = test_name in _initialized_test_dbs
    should_init_schema = (not initialized) or (not db_path.exists())
    conn = open_db(db_path)
    if should_init_schema:
        try:
            init_schema(conn)
        except Exception:
            conn.close()
            raise
        with _initialized_test_dbs_lock:
            _initialized_test_dbs.add(test_name)
    return conn, db_path


def _test_db_path(test_name: str) -> Path:
    """Build the per-test SQLite path for a test name.

    Args:
        test_name: Slug name of the testing flow.

    Returns:
        Path to the test database file.
    """
    return test_data_root() / f"{test_name}-test-data.sqlite"


def _with_test_db(test_name: str, fn: Callable[[Any], Any]) -> Any:
    """Open/close a test DB connection around one operation."""
    with _test_db_init_lock(test_name):
        conn, _ = _open_test_db_locked(test_name)
        try:
            return fn(conn)
        finally:
            conn.close()


def _handle_request(
    app: Flask,
    action: Callable[[], Any],
    *,
    log_message: str,
    bad_request_error: str | None = "invalid json",
    internal_error: str = "internal server error",
) -> Any:
    """Execute one request handler with consistent error mapping."""
    try:
        return action()
    except BadRequestError as exc:
        message = bad_request_error if bad_request_error is not None else str(exc)
        return jsonify({"error": message}), 400
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:  # pragma: no cover - defensive API surface
        app.logger.exception("%s", log_message)
        return jsonify({"error": internal_error}), 500


def create_main_app(cfg: Config) -> Flask:
    """Create main API application bound to production DB path."""
    app = Flask("aggregation-main")
    init_conn = _open_main_db()
    try:
        init_schema(init_conn)
    finally:
        init_conn.close()

    def _get_conn():
        """Get or lazily create a request-scoped main DB connection.

        Args:
            None.

        Returns:
            Open SQLite connection stored in Flask `g`.
        """
        conn = g.get("main_db_conn")
        if conn is None:
            conn = _open_main_db()
            g.main_db_conn = conn
        return conn

    @app.teardown_appcontext
    def _teardown_main_conn(_exception):
        """Close any request-scoped main DB connection at teardown.

        Args:
            _exception: Flask teardown exception object, if any.

        Returns:
            None.
        """
        conn = g.pop("main_db_conn", None)
        if conn is not None:
            conn.close()

    @app.get("/v1/health")
    def health():
        """Return main API health state.

        Args:
            None.

        Returns:
            Flask JSON response declaring service status.
        """
        return jsonify({"status": "ok"})

    @app.post("/v1/controls")
    def controls():
        """Create or update control metadata in the main database.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(
                request,
                required=["controlId", "controlType", "numStates"],
                optional=["stateLabels"],
            )
            control, _ = _validate_control_payload(payload, require_test_name=False)
            conn = _get_conn()
            upsert_control(conn, control)
            return jsonify({"status": "accepted"}), 202

        return _handle_request(app, _action, log_message="controls endpoint failed")

    @app.post("/v1/holding-intervals")
    def holding_intervals():
        """Ingest a holding interval into main aggregates.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(
                request,
                required=["controlId", "modelId", "state", "startTimeMs", "endTimeMs"],
            )
            input_data, _ = _validate_holding_payload(payload, require_test_name=False)
            conn = _get_conn()
            ingest_holding(conn, cfg, input_data)
            return jsonify({"status": "accepted"}), 202

        return _handle_request(app, _action, log_message="holding_intervals endpoint failed")

    @app.post("/v1/transitions")
    def transitions():
        """Ingest a transition event into main aggregates.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(
                request,
                required=["controlId", "modelId", "fromState", "toState", "timestampMs"],
            )
            input_data, _ = _validate_transition_payload(payload, require_test_name=False)
            conn = _get_conn()
            ingest_transition(conn, cfg, input_data)
            return jsonify({"status": "accepted"}), 202

        return _handle_request(app, _action, log_message="transitions endpoint failed")

    @app.post("/v1/snapshots")
    def snapshots():
        """Export a production snapshot from the main database.

        Args:
            None.

        Returns:
            Flask response tuple with exported snapshot metadata.
        """
        def _action():
            decode_strict_json(request, required=[])
            conn = _get_conn()
            path = export_snapshot(conn)
            return jsonify({"snapshotPath": str(path)}), 200

        return _handle_request(
            app,
            _action,
            log_message="snapshot export failed",
            bad_request_error=None,
            internal_error="snapshot export failed",
        )

    return app


def create_testing_app(cfg: Config) -> Flask:
    """Create testing API application with isolated per-test DB paths."""
    app = Flask("aggregation-testing")

    @app.get("/v1/health")
    def health():
        """Return testing API health state.

        Args:
            None.

        Returns:
            Flask JSON response declaring service status.
        """
        return jsonify({"status": "ok"})

    @app.post("/v1/controls")
    def controls():
        """Create or update control metadata in a test database.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(
                request,
                required=["testName", "controlId", "controlType", "numStates"],
                optional=["stateLabels"],
            )
            control, test_name = _validate_control_payload(payload, require_test_name=True)
            _with_test_db(test_name, lambda conn: upsert_control(conn, control))
            return jsonify({"status": "accepted"}), 202

        return _handle_request(app, _action, log_message="testing controls endpoint failed")

    @app.post("/v1/holding-intervals")
    def holding_intervals():
        """Ingest a holding interval into a test database aggregate set.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(
                request,
                required=["testName", "controlId", "modelId", "state", "startTimeMs", "endTimeMs"],
            )
            input_data, test_name = _validate_holding_payload(payload, require_test_name=True)
            _with_test_db(test_name, lambda conn: ingest_holding(conn, cfg, input_data))
            return jsonify({"status": "accepted"}), 202

        return _handle_request(app, _action, log_message="testing holding_intervals endpoint failed")

    @app.post("/v1/transitions")
    def transitions():
        """Ingest a transition event into a test database aggregate set.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(
                request,
                required=["testName", "controlId", "modelId", "fromState", "toState", "timestampMs"],
            )
            input_data, test_name = _validate_transition_payload(payload, require_test_name=True)
            _with_test_db(test_name, lambda conn: ingest_transition(conn, cfg, input_data))
            return jsonify({"status": "accepted"}), 202

        return _handle_request(app, _action, log_message="testing transitions endpoint failed")

    @app.post("/v1/snapshots")
    def snapshots():
        """Export a named snapshot file for a specific test database.

        Args:
            None.

        Returns:
            Flask response tuple with snapshot metadata.
        """
        def _action():
            payload = decode_strict_json(request, required=["testName", "snapshotName"])
            test_name = payload["testName"]
            snapshot_name = payload["snapshotName"]
            if not isinstance(test_name, str) or not is_valid_slug(test_name):
                raise ValidationError("invalid testName")
            if not isinstance(snapshot_name, str) or not is_valid_slug(snapshot_name):
                raise ValidationError("invalid snapshotName")
            def _write(conn):
                path = export_snapshot_for_test(conn, test_name, snapshot_name)
                return path
            path = _with_test_db(test_name, _write)
            return jsonify({"snapshotName": snapshot_name, "snapshotPath": str(path)}), 200

        return _handle_request(
            app,
            _action,
            log_message="snapshot export failed for testing api",
            internal_error="snapshot export failed",
        )

    @app.post("/v1/reset")
    def reset():
        """Delete a test database and its SQLite sidecar files.

        Args:
            None.

        Returns:
            Flask response tuple with JSON payload and HTTP status.
        """
        def _action():
            payload = decode_strict_json(request, required=["testName"])
            test_name = payload["testName"]
            if not isinstance(test_name, str) or not is_valid_slug(test_name):
                raise ValidationError("invalid testName")
            db_path = _test_db_path(test_name)
            with _test_db_init_lock(test_name):
                reset_test_db_files(db_path)
                with _initialized_test_dbs_lock:
                    _initialized_test_dbs.discard(test_name)
            return jsonify({"status": "ok"}), 200

        return _handle_request(app, _action, log_message="testing reset endpoint failed")

    return app
