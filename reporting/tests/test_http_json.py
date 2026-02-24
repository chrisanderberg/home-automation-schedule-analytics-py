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


if __name__ == "__main__":
    unittest.main()
