"""Quarter split behavior tests."""

import unittest

from shared_logic.quarter import quarter_index_utc, split_interval_utc


class QuarterTests(unittest.TestCase):
    def test_quarter_index_epoch(self):
        # Verifies epoch timestamp maps to canonical quarter index 0.
        self.assertEqual(quarter_index_utc(0), 0)

    def test_split_crosses_quarter_boundary(self):
        # Verifies intervals crossing UTC quarter boundary split into two spans.
        # 2024-03-31 23:59:00 UTC to 2024-04-01 00:01:00 UTC
        start_ms = 1711929540000
        end_ms = 1711929660000
        spans = split_interval_utc(start_ms, end_ms)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0].quarter_index, 216)  # 2024 Q1
        self.assertEqual(spans[1].quarter_index, 217)  # 2024 Q2

    def test_split_within_same_quarter(self):
        # Verifies a same-quarter interval yields exactly one span.
        start_ms = 1710043200000  # 2024-03-10T12:00:00Z
        end_ms = 1710046800000  # 2024-03-10T13:00:00Z
        spans = split_interval_utc(start_ms, end_ms)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].quarter_index, 216)

    def test_split_spans_multiple_quarters(self):
        # Verifies intervals crossing 3+ quarters produce increasing quarter indices.
        start_ms = 1711929540000  # 2024-03-31T23:59:00Z (Q1)
        end_ms = 1735689660000  # 2024-12-31T23:21:00Z (Q4)
        spans = split_interval_utc(start_ms, end_ms)
        self.assertGreaterEqual(len(spans), 3)
        indices = [span.quarter_index for span in spans]
        self.assertEqual(indices, sorted(indices))

    def test_split_rejects_zero_length_interval(self):
        # Verifies zero-length intervals are rejected.
        with self.assertRaises(ValueError):
            split_interval_utc(1710043200000, 1710043200000)

    def test_split_rejects_inverted_interval(self):
        # Verifies end-before-start intervals are rejected.
        with self.assertRaises(ValueError):
            split_interval_utc(1710046800000, 1710043200000)


if __name__ == "__main__":
    unittest.main()
