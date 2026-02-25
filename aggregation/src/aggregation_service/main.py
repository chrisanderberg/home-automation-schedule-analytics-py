"""Dual-port Flask service entrypoint."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from errno import EACCES, EADDRINUSE
from dataclasses import dataclass
from typing import Any

from werkzeug.serving import make_server

from aggregation_service.bootstrap import ensure_repo_src_paths

ensure_repo_src_paths()

from aggregation_service.app_factory import create_main_app, create_testing_app  # noqa: E402
from shared_logic.contracts import Config  # noqa: E402

logger = logging.getLogger(__name__)

# Main API listens on loopback by default; set HAA_MAIN_HOST=0.0.0.0 to opt into external binding.
_DEFAULT_MAIN_HOST = "127.0.0.1"
_DEFAULT_TESTING_HOST = "127.0.0.1"


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing."""


class PortBindError(OSError):
    """Wrap bind failures with the port that failed."""

    def __init__(self, failing_port: int, cause: OSError):
        super().__init__(cause.errno, cause.strerror or str(cause))
        self.failing_port = failing_port


@dataclass
class ServerThread:
    """Thread wrapper around a werkzeug WSGI server."""

    server: Any
    thread: threading.Thread


class ServerController:
    """Start and stop both API servers together."""

    def __init__(
        self,
        cfg: Config,
        main_port: int = 8080,
        testing_port: int = 8081,
        *,
        main_host: str = _DEFAULT_MAIN_HOST,
        testing_host: str = _DEFAULT_TESTING_HOST,
    ):
        """Create both WSGI servers and thread wrappers.

        Args:
            cfg: Runtime clock/location configuration shared by both apps.
            main_port: Port for the main API server.
            testing_port: Port for the testing API server.
            main_host: Host/interface for the main API server. Keyword-only.
            testing_host: Host/interface for the testing API server. Keyword-only.
        """
        self._stop = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        main_app = create_main_app(cfg)
        try:
            self.main_server = make_server(main_host, main_port, main_app)
        except OSError as exc:
            raise PortBindError(main_port, exc) from exc
        try:
            testing_app = create_testing_app(cfg)
        except Exception:
            self.main_server.server_close()
            raise
        try:
            self.testing_server = make_server(testing_host, testing_port, testing_app)
        except OSError as exc:
            self.main_server.server_close()
            raise PortBindError(testing_port, exc) from exc
        except Exception:
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


def _load_ports() -> tuple[int, int]:
    """Load and validate main/testing port configuration.

    Args:
        None.

    Returns:
        Tuple `(main_port, testing_port)`.
    """
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
    if main_port == testing_port:
        raise ConfigurationError(
            f"HAA_MAIN_PORT and HAA_TESTING_PORT must differ (both were {main_port})"
        )
    return main_port, testing_port


def _load_bind_hosts() -> tuple[str, str]:
    """Load and validate bind host settings for the main and testing APIs.

    Environment:
        HAA_MAIN_HOST: Bind host for the main API. Defaults to 127.0.0.1 when
            unset or empty after stripping whitespace.
        HAA_TESTING_HOST: Bind host for the testing API. Defaults to 127.0.0.1
            when unset or empty after stripping whitespace.
        Both variables are read from ``os.environ``. When unset or empty after
        strip, the module-level constants ``_DEFAULT_MAIN_HOST`` and
        ``_DEFAULT_TESTING_HOST`` are used respectively.

    Returns:
        Tuple ``(main_host, testing_host)`` of validated host strings.

    Raises:
        ConfigurationError: If a host cannot be resolved via socket.getaddrinfo.
    """
    main_host = os.getenv("HAA_MAIN_HOST", _DEFAULT_MAIN_HOST).strip() or _DEFAULT_MAIN_HOST
    testing_host = os.getenv("HAA_TESTING_HOST", _DEFAULT_TESTING_HOST).strip() or _DEFAULT_TESTING_HOST

    for host, env_var in [(main_host, "HAA_MAIN_HOST"), (testing_host, "HAA_TESTING_HOST")]:
        try:
            socket.getaddrinfo(host, None)
        except OSError as exc:
            raise ConfigurationError(
                f"invalid {env_var}: host {host!r} cannot be resolved ({exc})"
            ) from exc

    return main_host, testing_host


def _create_server_controller(
    cfg: Config,
    *,
    main_port: int,
    testing_port: int,
    main_host: str = _DEFAULT_MAIN_HOST,
    testing_host: str = _DEFAULT_TESTING_HOST,
) -> ServerController:
    """Create a dual-server controller with explicit bind failure messaging.

    Args:
        cfg: Runtime configuration shared by both servers.
        main_port: Port for the main API server.
        testing_port: Port for the testing API server.
        main_host: Bind host/address for the main API server.
        testing_host: Bind host/address for the testing API server.

    Returns:
        Constructed `ServerController`.
    """
    try:
        return ServerController(
            cfg,
            main_port=main_port,
            testing_port=testing_port,
            main_host=main_host,
            testing_host=testing_host,
        )
    except OSError as exc:
        # ServerController.__init__ wraps bind failures in PortBindError with failing_port set;
        # prefer failing_port when present for accurate port context in error messages.
        if isinstance(exc, PortBindError):
            port_context = f"port {exc.failing_port}"
            if exc.errno == EADDRINUSE:
                raise ConfigurationError(
                    f"failed to bind API {port_context}: address already in use"
                ) from exc
            elif exc.errno == EACCES:
                raise ConfigurationError(
                    f"failed to bind API {port_context}: permission denied"
                ) from exc
            else:
                raise ConfigurationError(f"failed to bind API {port_context}: {exc}") from exc
        else:
            raise ConfigurationError(f"failed to bind API: {exc}") from exc


def run() -> int:
    """Start both APIs and block until shutdown.

    Args:
        None.

    Returns:
        Process exit code (`0` on normal shutdown).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = _load_config()
    main_port, testing_port = _load_ports()
    main_host, testing_host = _load_bind_hosts()
    controller = _create_server_controller(
        cfg,
        main_port=main_port,
        testing_port=testing_port,
        main_host=main_host,
        testing_host=testing_host,
    )

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
    logger.info("main API listening on %s:%s", main_host, main_port)
    logger.info("testing API listening on %s:%s", testing_host, testing_port)

    try:
        while controller.should_run():
            time.sleep(0.2)
    finally:
        controller.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
