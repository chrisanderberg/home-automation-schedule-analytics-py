"""Quarter split behavior tests."""

from __future__ import annotations

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
        self.assertLess(spans[0].quarter_index, spans[1].quarter_index)


if __name__ == "__main__":
    unittest.main()
