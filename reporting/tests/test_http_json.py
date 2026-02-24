"""Reporting JSON helper tests."""

import unittest

from reporting_service.http_json import decode_json_body


class HttpJsonTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
