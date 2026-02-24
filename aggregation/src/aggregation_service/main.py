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
        self._stop = threading.Event()
        self._shutdown_started = False
        self.main_server = make_server("0.0.0.0", main_port, create_main_app(cfg))
        self.testing_server = make_server("0.0.0.0", testing_port, create_testing_app(cfg))
        self.threads = [
            ServerThread(self.main_server, threading.Thread(target=self.main_server.serve_forever, daemon=True)),
            ServerThread(
                self.testing_server,
                threading.Thread(target=self.testing_server.serve_forever, daemon=True),
            ),
        ]

    def start(self) -> None:
        for item in self.threads:
            item.thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._stop.set()
        for item in self.threads:
            item.server.shutdown()
        for item in self.threads:
            item.thread.join(timeout=5)
            if item.thread.is_alive():
                logger.warning("server thread did not stop cleanly: %r", item.thread)


def _load_config() -> Config:
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
    return Config(time_zone=time_zone, latitude=latitude, longitude=longitude)


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = _load_config()
    main_port = int(os.getenv("HAA_MAIN_PORT", "8080"))
    testing_port = int(os.getenv("HAA_TESTING_PORT", "8081"))

    controller = ServerController(cfg, main_port=main_port, testing_port=testing_port)

    def _handle_signal(_signum, _frame):
        controller.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    controller.start()
    logger.info("main API listening on :%s", main_port)
    logger.info("testing API listening on :%s", testing_port)

    try:
        while not controller._stop.is_set() and any(item.thread.is_alive() for item in controller.threads):
            time.sleep(0.2)
    finally:
        controller.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
