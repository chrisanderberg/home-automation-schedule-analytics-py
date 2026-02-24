"""Flask application factories for main and testing APIs."""

from __future__ import annotations

import os
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


def _validate_control_payload(data: dict[str, Any], *, require_test_name: bool) -> tuple[Control, str | None]:
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
    if not isinstance(num_states, int) or num_states < 2 or num_states > 10:
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
    if not isinstance(state, int):
        raise ValidationError("invalid state")
    if not isinstance(start_time_ms, int):
        raise ValidationError("invalid startTimeMs")
    if not isinstance(end_time_ms, int):
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
    if not isinstance(from_state, int):
        raise ValidationError("invalid fromState")
    if not isinstance(to_state, int):
        raise ValidationError("invalid toState")
    if not isinstance(timestamp_ms, int):
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
    override = os.getenv("HAA_DB_PATH", "").strip()
    if override:
        return Path(override).resolve()
    return data_root() / "data.sqlite"


def _open_main_db():
    db_path = _main_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return open_db(db_path)


def _open_test_db(test_name: str):
    root = test_data_root()
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / f"{test_name}-test-data.sqlite"
    conn = open_db(db_path)
    init_schema(conn)
    return conn, db_path


def _test_db_path(test_name: str) -> Path:
    return test_data_root() / f"{test_name}-test-data.sqlite"


def create_main_app(cfg: Config) -> Flask:
    """Create main API application bound to production DB path."""
    app = Flask("aggregation-main")
    init_conn = _open_main_db()
    try:
        init_schema(init_conn)
    finally:
        init_conn.close()

    def _get_conn():
        conn = g.get("main_db_conn")
        if conn is None:
            conn = _open_main_db()
            g.main_db_conn = conn
        return conn

    @app.teardown_appcontext
    def _teardown_main_conn(_exception):
        conn = g.pop("main_db_conn", None)
        if conn is not None:
            conn.close()

    @app.get("/v1/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/v1/controls")
    def controls():
        try:
            payload = decode_strict_json(
                request,
                required=["controlId", "controlType", "numStates"],
                optional=["stateLabels"],
            )
            control, _ = _validate_control_payload(payload, require_test_name=False)
            conn = _get_conn()
            upsert_control(conn, control)
            return jsonify({"status": "accepted"}), 202
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/v1/holding-intervals")
    def holding_intervals():
        try:
            payload = decode_strict_json(
                request,
                required=["controlId", "modelId", "state", "startTimeMs", "endTimeMs"],
            )
            input_data, _ = _validate_holding_payload(payload, require_test_name=False)
            conn = _get_conn()
            ingest_holding(conn, cfg, input_data)
            return jsonify({"status": "accepted"}), 202
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/v1/transitions")
    def transitions():
        try:
            payload = decode_strict_json(
                request,
                required=["controlId", "modelId", "fromState", "toState", "timestampMs"],
            )
            input_data, _ = _validate_transition_payload(payload, require_test_name=False)
            conn = _get_conn()
            ingest_transition(conn, cfg, input_data)
            return jsonify({"status": "accepted"}), 202
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/v1/snapshots")
    def snapshots():
        try:
            decode_strict_json(request, required=[])
            conn = _get_conn()
            path = export_snapshot(conn)
            return jsonify({"snapshotPath": str(path)}), 200
        except BadRequestError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pragma: no cover - defensive API surface
            app.logger.exception("snapshot export failed: %s", exc)
            return jsonify({"error": "snapshot export failed"}), 500

    return app


def create_testing_app(cfg: Config) -> Flask:
    """Create testing API application with isolated per-test DB paths."""
    app = Flask("aggregation-testing")

    @app.get("/v1/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/v1/controls")
    def controls():
        try:
            payload = decode_strict_json(
                request,
                required=["testName", "controlId", "controlType", "numStates"],
                optional=["stateLabels"],
            )
            control, test_name = _validate_control_payload(payload, require_test_name=True)
            conn, _ = _open_test_db(str(test_name))
            try:
                upsert_control(conn, control)
            finally:
                conn.close()
            return jsonify({"status": "accepted"}), 202
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/v1/holding-intervals")
    def holding_intervals():
        try:
            payload = decode_strict_json(
                request,
                required=["testName", "controlId", "modelId", "state", "startTimeMs", "endTimeMs"],
            )
            input_data, test_name = _validate_holding_payload(payload, require_test_name=True)
            conn, _ = _open_test_db(str(test_name))
            try:
                ingest_holding(conn, cfg, input_data)
            finally:
                conn.close()
            return jsonify({"status": "accepted"}), 202
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            if exc.field == "testName":
                return jsonify({"error": str(exc)}), 400
            return jsonify({"error": "invalid input"}), 400

    @app.post("/v1/transitions")
    def transitions():
        try:
            payload = decode_strict_json(
                request,
                required=["testName", "controlId", "modelId", "fromState", "toState", "timestampMs"],
            )
            input_data, test_name = _validate_transition_payload(payload, require_test_name=True)
            conn, _ = _open_test_db(str(test_name))
            try:
                ingest_transition(conn, cfg, input_data)
            finally:
                conn.close()
            return jsonify({"status": "accepted"}), 202
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            if exc.field == "testName":
                return jsonify({"error": str(exc)}), 400
            return jsonify({"error": "invalid input"}), 400

    @app.post("/v1/snapshots")
    def snapshots():
        try:
            payload = decode_strict_json(request, required=["testName", "snapshotName"])
            test_name = payload["testName"]
            snapshot_name = payload["snapshotName"]
            if not isinstance(test_name, str) or not is_valid_slug(test_name):
                raise ValidationError("invalid testName")
            if not isinstance(snapshot_name, str) or not is_valid_slug(snapshot_name):
                raise ValidationError("invalid snapshotName")
            conn, _ = _open_test_db(test_name)
            try:
                path = export_snapshot_for_test(conn, test_name, snapshot_name)
            finally:
                conn.close()
            return jsonify({"snapshotName": snapshot_name, "snapshotPath": str(path)}), 200
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pragma: no cover - defensive API surface
            app.logger.exception("snapshot export failed for testing api: %s", exc)
            return jsonify({"error": "snapshot export failed"}), 500

    @app.post("/v1/reset")
    def reset():
        try:
            payload = decode_strict_json(request, required=["testName"])
            test_name = payload["testName"]
            if not isinstance(test_name, str) or not is_valid_slug(test_name):
                raise ValidationError("invalid testName")
            db_path = _test_db_path(test_name)
            reset_test_db_files(db_path)
            return jsonify({"status": "ok"}), 200
        except BadRequestError:
            return jsonify({"error": "invalid json"}), 400
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    return app
