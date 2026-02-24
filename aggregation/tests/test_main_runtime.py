"""Runtime configuration and controller creation tests."""

from __future__ import annotations

import errno
import os
import unittest
from unittest.mock import patch

from aggregation_service.main import ConfigurationError, _create_server_controller, _load_ports
from shared_logic.contracts import Config


class MainRuntimeTests(unittest.TestCase):
    def test_load_ports_rejects_duplicate_values(self):
        # Verifies main/testing ports cannot be configured to the same value.
        with patch.dict(os.environ, {"HAA_MAIN_PORT": "8080", "HAA_TESTING_PORT": "8080"}, clear=False):
            with self.assertRaisesRegex(ConfigurationError, "must differ"):
                _load_ports()

    def test_create_server_controller_wraps_address_in_use(self):
        # Verifies bind failures are surfaced as explicit configuration errors.
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        bind_error = OSError(errno.EADDRINUSE, "Address already in use")
        with patch("aggregation_service.main.ServerController", side_effect=bind_error):
            with self.assertRaisesRegex(ConfigurationError, "address already in use"):
                _create_server_controller(cfg, main_port=8080, testing_port=8081)


if __name__ == "__main__":
    unittest.main()
