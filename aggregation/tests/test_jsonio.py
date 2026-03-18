"""Focused tests for the strict request-body decoder used by the Flask API."""

from __future__ import annotations

import unittest

from flask import Flask, request

from aggregation_service.jsonio import BadRequestError, decode_strict_json


class JsonIoTests(unittest.TestCase):
    """Document the request-shape contract once at the helper layer."""

    def setUp(self):
        """A tiny Flask app is enough to manufacture realistic request objects."""
        self.app = Flask(__name__)

    def test_decode_strict_json_accepts_valid_object(self):
        """The happy path allows only object payloads with the expected keys."""
        with self.app.test_request_context(
            "/",
            method="POST",
            json={"required": 1, "optional": 2},
        ):
            decoded = decode_strict_json(request, required=["required"], optional=["optional"])
        self.assertEqual(decoded, {"required": 1, "optional": 2})

    def test_decode_strict_json_rejects_non_json_content_type(self):
        with self.app.test_request_context("/", method="POST", data="a=1", content_type="text/plain"):
            with self.assertRaisesRegex(BadRequestError, "Content-Type"):
                decode_strict_json(request, required=["required"])

    def test_decode_strict_json_rejects_malformed_json(self):
        with self.app.test_request_context("/", method="POST", data="{bad", content_type="application/json"):
            with self.assertRaisesRegex(BadRequestError, "invalid json body"):
                decode_strict_json(request, required=["required"])

    def test_decode_strict_json_rejects_non_object_payload(self):
        """Lists are valid JSON, but not valid request bodies for these endpoints."""
        with self.app.test_request_context("/", method="POST", json=[1, 2, 3]):
            with self.assertRaisesRegex(BadRequestError, "must be an object"):
                decode_strict_json(request, required=["required"])

    def test_decode_strict_json_rejects_missing_required_fields(self):
        with self.app.test_request_context("/", method="POST", json={"optional": 2}):
            with self.assertRaisesRegex(BadRequestError, "missing required fields"):
                decode_strict_json(request, required=["required"], optional=["optional"])

    def test_decode_strict_json_rejects_unknown_fields(self):
        with self.app.test_request_context("/", method="POST", json={"required": 1, "extra": 2}):
            with self.assertRaisesRegex(BadRequestError, "unknown fields"):
                decode_strict_json(request, required=["required"])


if __name__ == "__main__":
    unittest.main()
