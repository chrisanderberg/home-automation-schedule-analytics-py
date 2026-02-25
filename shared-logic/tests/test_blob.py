"""Blob/index invariants tests."""

from __future__ import annotations

import unittest

from shared_logic.blob import Blob, CLOCK_UTC, hold_index, trans_index


class BlobTests(unittest.TestCase):
    def test_blob_roundtrip_u64(self):
        # Verifies little-endian u64 writes can be read back at the same index.
        blob = Blob(2)
        idx = hold_index(1, CLOCK_UTC, 10, 2)
        blob.set_u64(idx, 123)
        self.assertEqual(blob.get_u64(idx), 123)

    def test_transition_index_rejects_self(self):
        # Verifies self-transition index computation is rejected by invariant.
        with self.assertRaises(ValueError):
            trans_index(1, 1, CLOCK_UTC, 10, 2)

    def test_transition_index_accepts_non_self(self):
        # Verifies a non-self transition index can be written/read via Blob u64 accessors.
        blob = Blob(2)
        idx = trans_index(0, 1, CLOCK_UTC, 10, 2)
        blob.set_u64(idx, 7)
        self.assertEqual(blob.get_u64(idx), 7)


if __name__ == "__main__":
    unittest.main()
