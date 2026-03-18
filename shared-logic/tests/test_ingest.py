"""Ingestion tests that document how events map into persisted aggregate blobs."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from shared_logic.blob import (
    Blob,
    CLOCK_APPARENT_SOLAR,
    CLOCK_LOCAL,
    CLOCK_MEAN_SOLAR,
    CLOCK_UNEQUAL_HOURS,
    CLOCK_UTC,
    hold_index,
    trans_index,
)
from shared_logic.bucketing import (
    bucket_at_apparent_solar,
    bucket_at_local,
    bucket_at_mean_solar,
    bucket_at_unequal_hours,
    bucket_at_utc,
    split_interval_apparent_solar,
    split_interval_local,
    split_interval_mean_solar,
    split_interval_unequal_hours,
    split_interval_utc,
)
from shared_logic.contracts import Config, Control, HoldingInput, TransitionInput
from shared_logic.errors import UndefinedClockError, ValidationError
from shared_logic.quarter import quarter_index_utc
from shared_logic.ingest import ingest_holding, ingest_transition
from shared_logic.storage import init_schema, open_db, upsert_control


class IngestTests(unittest.TestCase):
    def _make_conn_and_control(self, *, num_states: int = 3):
        """Create a temporary sqlite DB with one declared control ready for ingest."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = open_db(Path(tmp.name) / "test.sqlite")
        self.addCleanup(conn.close)
        init_schema(conn)
        upsert_control(
            conn,
            Control(control_id="mode", control_type="discrete", num_states=num_states),
        )
        return conn

    def _load_blob(self, conn, *, model_id: str, quarter_index: int, num_states: int):
        """Read one aggregate row back into a `Blob` for exact assertions."""
        raw = conn.execute(
            "SELECT blob FROM aggregates WHERE control_id=? AND model_id=? AND quarter_index=?",
            ("mode", model_id, quarter_index),
        ).fetchone()[0]
        return Blob(num_states, raw)

    def test_holding_and_transition_ingest(self):
        # Verifies holding+transition ingestion persists one aggregate row for a valid control/model/quarter.
        conn = self._make_conn_and_control()
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

    def test_holding_ingest_updates_expected_blob_bucket_counts(self):
        """Compare persisted holding counters against the exact splitter output for each clock."""
        conn = self._make_conn_and_control()
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        start_ms = 1704067200000
        end_ms = 1704067500000
        ingest_holding(
            conn,
            cfg,
            HoldingInput(
                control_id="mode",
                model_id="m1",
                state=1,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
        )

        blob = self._load_blob(conn, model_id="m1", quarter_index=quarter_index_utc(start_ms), num_states=3)
        splitters = [
            (CLOCK_UTC, split_interval_utc(start_ms, end_ms)),
            (CLOCK_LOCAL, split_interval_local(start_ms, end_ms, cfg.time_zone)),
            (CLOCK_MEAN_SOLAR, split_interval_mean_solar(start_ms, end_ms, cfg.latitude, cfg.longitude)),
            (CLOCK_APPARENT_SOLAR, split_interval_apparent_solar(start_ms, end_ms, cfg.latitude, cfg.longitude)),
            (CLOCK_UNEQUAL_HOURS, split_interval_unequal_hours(start_ms, end_ms, cfg.latitude, cfg.longitude)),
        ]

        for clock_idx, spans in splitters:
            total = 0
            for span in spans:
                idx = hold_index(1, clock_idx, span.bucket, 3)
                self.assertEqual(blob.get_u64(idx), span.millis)
                total += span.millis
            self.assertEqual(total, end_ms - start_ms)

    def test_transition_ingest_updates_expected_transition_counts(self):
        conn = self._make_conn_and_control()
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        timestamp_ms = 1704067500000
        ingest_transition(
            conn,
            cfg,
            TransitionInput(
                control_id="mode",
                model_id="m1",
                from_state=1,
                to_state=2,
                timestamp_ms=timestamp_ms,
            ),
        )

        blob = self._load_blob(conn, model_id="m1", quarter_index=quarter_index_utc(timestamp_ms), num_states=3)
        buckets = [
            (CLOCK_UTC, bucket_at_utc(timestamp_ms)),
            (CLOCK_LOCAL, bucket_at_local(timestamp_ms, cfg.time_zone)),
            (CLOCK_MEAN_SOLAR, bucket_at_mean_solar(timestamp_ms, cfg.latitude, cfg.longitude)),
            (CLOCK_APPARENT_SOLAR, bucket_at_apparent_solar(timestamp_ms, cfg.latitude, cfg.longitude)),
            (CLOCK_UNEQUAL_HOURS, bucket_at_unequal_hours(timestamp_ms, cfg.latitude, cfg.longitude)),
        ]
        for clock_idx, bucket in buckets:
            idx = trans_index(1, 2, clock_idx, bucket, 3)
            self.assertEqual(blob.get_u64(idx), 1)

    def test_holding_ingest_splits_across_multiple_quarter_rows(self):
        """A quarter boundary should create two rows instead of smearing time across one blob."""
        conn = self._make_conn_and_control()
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        start_ms = 1711929540000
        end_ms = 1711929660000
        ingest_holding(
            conn,
            cfg,
            HoldingInput(
                control_id="mode",
                model_id="m1",
                state=1,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
        )

        rows = conn.execute(
            "SELECT quarter_index, blob FROM aggregates WHERE control_id=? AND model_id=? ORDER BY quarter_index",
            ("mode", "m1"),
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [216, 217])
        first_blob = Blob(3, rows[0][1])
        second_blob = Blob(3, rows[1][1])
        # 2024-03-31 23:59 UTC is the last bucket of Q1; 2024-04-01 00:00 UTC is the first of Q2.
        self.assertEqual(first_blob.get_u64(hold_index(1, CLOCK_UTC, 2015, 3)), 60000)
        self.assertEqual(second_blob.get_u64(hold_index(1, CLOCK_UTC, 0, 3)), 60000)

    def test_ingest_holding_rejects_unknown_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "test.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
            with self.assertRaisesRegex(ValidationError, "unknown control"):
                ingest_holding(
                    conn,
                    cfg,
                    HoldingInput(
                        control_id="missing",
                        model_id="m1",
                        state=0,
                        start_time_ms=1704067200000,
                        end_time_ms=1704067500000,
                    ),
                )

    def test_ingest_holding_rejects_state_out_of_range(self):
        conn = self._make_conn_and_control(num_states=2)
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        with self.assertRaisesRegex(ValidationError, "invalid input"):
            ingest_holding(
                conn,
                cfg,
                HoldingInput(
                    control_id="mode",
                    model_id="m1",
                    state=2,
                    start_time_ms=1704067200000,
                    end_time_ms=1704067500000,
                ),
            )

    def test_ingest_transition_rejects_unknown_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = open_db(Path(tmp) / "test.sqlite")
            self.addCleanup(conn.close)
            init_schema(conn)
            cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
            with self.assertRaisesRegex(ValidationError, "unknown control"):
                ingest_transition(
                    conn,
                    cfg,
                    TransitionInput(
                        control_id="missing",
                        model_id="m1",
                        from_state=0,
                        to_state=1,
                        timestamp_ms=1704067500000,
                    ),
                )

    def test_ingest_transition_rejects_state_out_of_range(self):
        conn = self._make_conn_and_control(num_states=2)
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        with self.assertRaisesRegex(ValidationError, "invalid input"):
            ingest_transition(
                conn,
                cfg,
                TransitionInput(
                    control_id="mode",
                    model_id="m1",
                    from_state=0,
                    to_state=2,
                    timestamp_ms=1704067500000,
                ),
            )

    def test_ingest_transition_rejects_self_transition(self):
        conn = self._make_conn_and_control()
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        with self.assertRaises(ValueError):
            TransitionInput(
                control_id="mode",
                model_id="m1",
                from_state=1,
                to_state=1,
                timestamp_ms=1704067500000,
            )

    def test_ingest_transition_rejects_negative_state_indices(self):
        with self.assertRaisesRegex(ValueError, "from_state must be non-negative"):
            TransitionInput(
                control_id="mode",
                model_id="m1",
                from_state=-1,
                to_state=1,
                timestamp_ms=1704067500000,
            )
        with self.assertRaisesRegex(ValueError, "to_state must be non-negative"):
            TransitionInput(
                control_id="mode",
                model_id="m1",
                from_state=1,
                to_state=-1,
                timestamp_ms=1704067500000,
            )

    def test_ingest_skips_undefined_clock_calculations_without_failing(self):
        """One undefined clock should not block ingest for the other clock families."""
        conn = self._make_conn_and_control()
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        with patch("shared_logic.ingest.split_interval_unequal_hours", side_effect=UndefinedClockError("undefined")):
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
        blob = self._load_blob(conn, model_id="m1", quarter_index=quarter_index_utc(1704067200000), num_states=3)
        self.assertEqual(blob.get_u64(hold_index(1, CLOCK_UNEQUAL_HOURS, 0, 3)), 0)
        self.assertGreater(blob.get_u64(hold_index(1, CLOCK_LOCAL, 0, 3)), 0)

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
