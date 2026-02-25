"""Ingestion smoke tests."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from shared_logic.contracts import Config, Control, HoldingInput, TransitionInput
from shared_logic.ingest import ingest_holding, ingest_transition
from shared_logic.storage import init_schema, open_db, upsert_control


class IngestTests(unittest.TestCase):
    def test_holding_and_transition_ingest(self):
        # Verifies holding+transition ingestion persists one aggregate row for a valid control/model/quarter.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            conn = None
            try:
                conn = open_db(db_path)
                init_schema(conn)
                upsert_control(
                    conn,
                    Control(control_id="mode", control_type="discrete", num_states=3),
                )
                cfg = Config(time_zone="UTC", latitude=37.77, longitude=-122.42)
                ingest_holding(
                    conn,
                    cfg,
                    HoldingInput(
                        control_id="mode",
                        model_id="m1",
                        state=1,
                        start_time_ms=1704067200000,
                        end_time_ms=1704067500000,
                    ),
                )
                ingest_transition(
                    conn,
                    cfg,
                    TransitionInput(
                        control_id="mode",
                        model_id="m1",
                        from_state=1,
                        to_state=2,
                        timestamp_ms=1704067500000,
                    ),
                )
                agg_count = conn.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0]
                self.assertEqual(agg_count, 1)
            finally:
                if conn is not None:
                    conn.close()

    def test_connection_can_be_used_from_server_thread(self):
        # Verifies open_db disables sqlite thread affinity checks for server-thread request handling.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "thread-test.sqlite"
            conn = None
            try:
                conn = open_db(db_path)
                init_schema(conn)
                error_box: list[Exception] = []

                def _worker() -> None:
                    try:
                        conn.execute("SELECT 1").fetchone()
                    except Exception as exc:  # pragma: no cover
                        error_box.append(exc)

                thread = threading.Thread(target=_worker)
                thread.start()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive(), "worker thread did not finish in time")
                self.assertEqual(error_box, [])
            finally:
                if conn is not None:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
