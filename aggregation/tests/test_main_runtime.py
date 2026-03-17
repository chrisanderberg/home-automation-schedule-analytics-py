"""Tests for runtime configuration loading and controller edge cases."""

from __future__ import annotations

import errno
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aggregation_service.main import (
    ConfigurationError,
    PortBindError,
    ServerController,
    _create_server_controller,
    _load_bind_hosts,
    _load_config,
    _load_ports,
)
from shared_logic.contracts import Config


class MainRuntimeTests(unittest.TestCase):
    """Keep startup and shutdown failure modes explicit for future readers."""

    def test_load_config_requires_latitude_and_longitude(self):
        """Startup should fail fast rather than guessing a location."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "HAA_LATITUDE, HAA_LONGITUDE"):
                _load_config()

    def test_load_config_rejects_non_numeric_latitude_longitude(self):
        with patch.dict(os.environ, {"HAA_LATITUDE": "north", "HAA_LONGITUDE": "west"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "must be numeric"):
                _load_config()

    def test_load_config_rejects_out_of_range_latitude(self):
        with patch.dict(os.environ, {"HAA_LATITUDE": "91", "HAA_LONGITUDE": "0"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "between -90 and 90"):
                _load_config()

    def test_load_config_rejects_out_of_range_longitude(self):
        with patch.dict(os.environ, {"HAA_LATITUDE": "0", "HAA_LONGITUDE": "181"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "between -180 and 180"):
                _load_config()

    def test_load_ports_rejects_duplicate_values(self):
        # Verifies main/testing ports cannot be configured to the same value.
        with patch.dict(os.environ, {"HAA_MAIN_PORT": "8080", "HAA_TESTING_PORT": "8080"}):
            with self.assertRaisesRegex(ConfigurationError, "must differ"):
                _load_ports()

    def test_load_ports_rejects_non_numeric_main_port(self):
        with patch.dict(os.environ, {"HAA_MAIN_PORT": "nope", "HAA_TESTING_PORT": "8081"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "invalid HAA_MAIN_PORT"):
                _load_ports()

    def test_load_ports_rejects_out_of_range_testing_port(self):
        with patch.dict(os.environ, {"HAA_MAIN_PORT": "8080", "HAA_TESTING_PORT": "70000"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "invalid HAA_TESTING_PORT"):
                _load_ports()

    def test_load_bind_hosts_rejects_unresolvable_host(self):
        """Host validation exists so bad bind targets fail before server startup."""
        with patch.dict(os.environ, {"HAA_MAIN_HOST": "bad-host"}, clear=True):
            with patch("aggregation_service.main.socket.getaddrinfo", side_effect=OSError("no such host")):
                with self.assertRaisesRegex(ConfigurationError, "invalid HAA_MAIN_HOST"):
                    _load_bind_hosts()

    def test_create_server_controller_wraps_address_in_use(self):
        # Verifies bind failures are surfaced as explicit configuration errors.
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        bind_error = PortBindError(8081, OSError(errno.EADDRINUSE, "Address already in use"))
        with patch("aggregation_service.main.ServerController", side_effect=bind_error):
            with self.assertRaisesRegex(ConfigurationError, r"(?i)failed to bind api port 8081: address already in use"):
                _create_server_controller(cfg, main_port=8080, testing_port=8081)

    def test_create_server_controller_wraps_permission_denied(self):
        cfg = Config(time_zone="UTC", latitude=0.0, longitude=0.0)
        bind_error = PortBindError(8080, OSError(errno.EACCES, "Permission denied"))
        with patch("aggregation_service.main.ServerController", side_effect=bind_error):
            with self.assertRaisesRegex(ConfigurationError, r"(?i)permission denied"):
                _create_server_controller(cfg, main_port=8080, testing_port=8081)

    def test_server_controller_stop_is_idempotent(self):
        """Shutdown often runs from both signal and exception paths, so double-stop must be safe."""
        server_a = Mock()
        server_b = Mock()
        thread_a = Mock()
        thread_a.is_alive.return_value = False
        thread_b = Mock()
        thread_b.is_alive.return_value = False

        controller = object.__new__(ServerController)
        controller._stop = threading.Event()
        controller._shutdown_lock = threading.Lock()
        controller._shutdown_started = False
        controller.threads = [
            SimpleNamespace(server=server_a, thread=thread_a),
            SimpleNamespace(server=server_b, thread=thread_b),
        ]

        controller.stop()
        controller.stop()

        server_a.shutdown.assert_called_once()
        server_a.server_close.assert_called_once()
        server_b.shutdown.assert_called_once()
        server_b.server_close.assert_called_once()
        thread_a.join.assert_called_once()
        thread_b.join.assert_called_once()

    def test_server_controller_should_run_returns_false_after_request_stop(self):
        alive_thread = Mock()
        alive_thread.is_alive.return_value = True

        controller = object.__new__(ServerController)
        controller._stop = threading.Event()
        controller.threads = [SimpleNamespace(server=Mock(), thread=alive_thread)]

        controller.request_stop()

        self.assertFalse(controller.should_run())

    def test_server_controller_should_run_returns_false_when_thread_dies(self):
        """One dead worker thread should tear down the whole controller, not limp on half-alive."""
        dead_thread = Mock()
        dead_thread.is_alive.return_value = False

        controller = object.__new__(ServerController)
        controller._stop = threading.Event()
        controller.threads = [SimpleNamespace(server=Mock(), thread=dead_thread)]

        self.assertFalse(controller.should_run())
        self.assertTrue(controller._stop.is_set())


if __name__ == "__main__":
    unittest.main()
