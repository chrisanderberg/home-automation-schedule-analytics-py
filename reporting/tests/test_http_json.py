"""Tests for the small HTTP JSON decoding shim used by reporting assets."""

import unittest

from reporting_service.http_json import MAX_ERROR_BODY_CHARS, TRUNCATION_SUFFIX, decode_json_body


class HttpJsonTests(unittest.TestCase):
    """Keep the helper's fallback behavior explicit for future refactors."""

    def test_decode_object(self):
        # Verifies valid JSON object bodies decode as dictionaries.
        self.assertEqual(decode_json_body('{"a":1}', decode_error_as_error_payload=False), {"a": 1})

    def test_decode_invalid_as_error(self):
        # Verifies invalid JSON can be surfaced as an error payload when requested.
        self.assertEqual(decode_json_body("not-json", decode_error_as_error_payload=True), {"error": "not-json"})

    def test_decode_invalid_raises_when_error_payload_disabled(self):
        # Verifies invalid JSON is not silently swallowed when decode_error_as_error_payload is False.
        with self.assertRaises(ValueError):
            decode_json_body("not-json", decode_error_as_error_payload=False)

    def test_decode_non_object_json(self):
        # Verifies valid non-object JSON values are preserved.
        self.assertEqual(decode_json_body("[1,2]", decode_error_as_error_payload=False), [1, 2])

    def test_decode_empty_body_as_error_payload(self):
        # Verifies empty body returns explicit error payload when requested.
        self.assertEqual(decode_json_body("", decode_error_as_error_payload=True), {"error": ""})

    def test_decode_empty_body_raises_when_error_payload_disabled(self):
        # Verifies empty body raises consistently with other invalid JSON payloads.
        with self.assertRaises(ValueError):
            decode_json_body("", decode_error_as_error_payload=False)

    def test_decode_invalid_truncates_long_error_payload(self):
        # Verifies invalid payload errors are bounded and suffixed when too long.
        invalid = "x" * (MAX_ERROR_BODY_CHARS + 50)
        expected = invalid[: MAX_ERROR_BODY_CHARS - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX
        self.assertEqual(
            decode_json_body(invalid, decode_error_as_error_payload=True),
            {"error": expected},
        )

    def test_decode_invalid_multiline_payload_compacts_whitespace(self):
        # Tabs are preserved today; this locks in the current sanitization contract.
        self.assertEqual(
            decode_json_body("bad\njson\tpayload", decode_error_as_error_payload=True),
            {"error": "bad json\tpayload"},
        )

    def test_decode_invalid_whitespace_only_body_returns_unparseable_payload(self):
        self.assertEqual(
            decode_json_body("   \n\t", decode_error_as_error_payload=True),
            {"error": "unparseable payload"},
        )


if __name__ == "__main__":
    unittest.main()
