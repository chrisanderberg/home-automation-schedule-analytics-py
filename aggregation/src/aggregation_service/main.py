"""Dual-port Flask service entrypoint."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any

from werkzeug.serving import make_server

from aggregation_service.bootstrap import ensure_repo_src_paths

ensure_repo_src_paths()

from aggregation_service.app_factory import create_main_app, create_testing_app  # noqa: E402
from shared_logic.contracts import Config  # noqa: E402

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing."""


@dataclass
class ServerThread:
    """Thread wrapper around a werkzeug WSGI server."""

    server: Any
    thread: threading.Thread


class ServerController:
    """Start and stop both API servers together."""

    def __init__(self, cfg: Config, main_port: int = 8080, testing_port: int = 8081):
        """Create both WSGI servers and thread wrappers.

        Args:
            cfg: Runtime clock/location configuration shared by both apps.
            main_port: Port for the main API server.
            testing_port: Port for the testing API server.
        """
        self._stop = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self.main_server = make_server("0.0.0.0", main_port, create_main_app(cfg))
        try:
            self.testing_server = make_server("0.0.0.0", testing_port, create_testing_app(cfg))
        except Exception:
            self.main_server.shutdown()
            self.main_server.server_close()
            raise
        self.threads = [
            ServerThread(self.main_server, threading.Thread(target=self.main_server.serve_forever, daemon=True)),
            ServerThread(
                self.testing_server,
                threading.Thread(target=self.testing_server.serve_forever, daemon=True),
            ),
        ]

    def start(self) -> None:
        """Start both server threads.

        Args:
            None.

        Returns:
            None.
        """
        for item in self.threads:
            item.thread.start()

    def request_stop(self) -> None:
        """Signal the run loop to stop.

        Args:
            None.

        Returns:
            None.
        """
        self._stop.set()

    def should_run(self) -> bool:
        """Check whether servers should keep running.

        Args:
            None.

        Returns:
            `True` when no stop was requested and both threads are alive.
        """
        if self._stop.is_set():
            return False
        for item in self.threads:
            if not item.thread.is_alive():
                logger.error("server thread exited unexpectedly: %r (server=%r)", item.thread, item.server)
                self._stop.set()
                return False
        return True

    def stop(self) -> None:
        """Shut down both servers and join their threads.

        Args:
            None.

        Returns:
            None.
        """
        with self._shutdown_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
        self._stop.set()
        for item in self.threads:
            server = getattr(item, "server", None)
            if server is None:
                continue
            try:
                server.shutdown()
            finally:
                server.server_close()
        for item in self.threads:
            item.thread.join(timeout=5)
            if item.thread.is_alive():
                logger.warning("server thread did not stop cleanly: %r", item.thread)


def _load_config() -> Config:
    """Load and validate runtime configuration from environment variables.

    Args:
        None.

    Returns:
        Parsed `Config` object for ingestion clock calculations.
    """
    time_zone = os.getenv("HAA_TIMEZONE", "UTC")
    missing = [name for name in ("HAA_LATITUDE", "HAA_LONGITUDE") if not os.getenv(name)]
    if missing:
        joined = ", ".join(missing)
        raise ConfigurationError(f"missing required runtime env var(s): {joined}")
    try:
        latitude = float(os.environ["HAA_LATITUDE"])
        longitude = float(os.environ["HAA_LONGITUDE"])
    except ValueError as exc:
        raise ConfigurationError("HAA_LATITUDE and HAA_LONGITUDE must be numeric") from exc
    if not (-90.0 <= latitude <= 90.0):
        raise ConfigurationError("HAA_LATITUDE must be between -90 and 90")
    if not (-180.0 <= longitude <= 180.0):
        raise ConfigurationError("HAA_LONGITUDE must be between -180 and 180")
    return Config(time_zone=time_zone, latitude=latitude, longitude=longitude)


def run() -> int:
    """Start both APIs and block until shutdown.

    Args:
        None.

    Returns:
        Process exit code (`0` on normal shutdown).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = _load_config()
    main_port_raw = os.getenv("HAA_MAIN_PORT", "8080")
    testing_port_raw = os.getenv("HAA_TESTING_PORT", "8081")
    try:
        main_port = int(main_port_raw)
    except ValueError as exc:
        raise ConfigurationError(f"invalid HAA_MAIN_PORT value: {main_port_raw!r}") from exc
    if not (1 <= main_port <= 65535):
        raise ConfigurationError(f"invalid HAA_MAIN_PORT value: {main_port!r} (must be 1-65535)")
    try:
        testing_port = int(testing_port_raw)
    except ValueError as exc:
        raise ConfigurationError(f"invalid HAA_TESTING_PORT value: {testing_port_raw!r}") from exc
    if not (1 <= testing_port <= 65535):
        raise ConfigurationError(f"invalid HAA_TESTING_PORT value: {testing_port!r} (must be 1-65535)")

    controller = ServerController(cfg, main_port=main_port, testing_port=testing_port)

    def _handle_signal(_signum, _frame):
        """Handle SIGINT/SIGTERM by requesting coordinated shutdown.

        Args:
            _signum: Signal number provided by Python signal handler.
            _frame: Current execution frame (unused).

        Returns:
            None.
        """
        controller.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    controller.start()
    logger.info("main API listening on :%s", main_port)
    logger.info("testing API listening on :%s", testing_port)

    try:
        while controller.should_run():
            time.sleep(0.2)
    finally:
        controller.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
