"""Low-level blob and index invariants that higher-level ingest/storage rely on."""

from __future__ import annotations

import unittest

from shared_logic.blob import MAX_STATES, Blob, CLOCK_UTC, hold_index, trans_index


class BlobTests(unittest.TestCase):
    """Keep the compact blob layout readable by locking down the sharp edges."""

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

    def test_blob_constructor_rejects_invalid_raw_length(self):
        """Persisted aggregate blobs must match the exact expected byte length."""
        with self.assertRaisesRegex(ValueError, "blob size mismatch"):
            Blob(2, b"short")

    def test_hold_index_rejects_out_of_range_state(self):
        with self.assertRaises(IndexError):
            hold_index(2, CLOCK_UTC, 0, 2)

    def test_transition_index_rejects_out_of_range_state(self):
        with self.assertRaises(IndexError):
            trans_index(0, 2, CLOCK_UTC, 0, 2)

    def test_blob_roundtrip_with_max_supported_state_count(self):
        blob = Blob(MAX_STATES)
        idx = hold_index(MAX_STATES - 1, CLOCK_UTC, 0, MAX_STATES)
        blob.set_u64(idx, 456)
        self.assertEqual(blob.get_u64(idx), 456)


if __name__ == "__main__":
    unittest.main()
