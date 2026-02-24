"""Dual-port Flask service entrypoint."""

from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass

from werkzeug.serving import make_server

from aggregation_service.bootstrap import ensure_repo_src_paths

ensure_repo_src_paths()

from aggregation_service.app_factory import create_main_app, create_testing_app  # noqa: E402
from shared_logic.contracts import Config  # noqa: E402


@dataclass
class ServerThread:
    """Thread wrapper around a werkzeug WSGI server."""

    server: any
    thread: threading.Thread


class ServerController:
    """Start and stop both API servers together."""

    def __init__(self, cfg: Config, main_port: int = 8080, testing_port: int = 8081):
        self._stop = threading.Event()
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

    def stop(self) -> None:
        for item in self.threads:
            item.server.shutdown()
        for item in self.threads:
            item.thread.join(timeout=5)


def _load_config() -> Config:
    time_zone = os.getenv("HAA_TIMEZONE", "UTC")
    latitude = float(os.getenv("HAA_LATITUDE", "0"))
    longitude = float(os.getenv("HAA_LONGITUDE", "0"))
    return Config(time_zone=time_zone, latitude=latitude, longitude=longitude)


def run() -> int:
    cfg = _load_config()
    main_port = int(os.getenv("HAA_MAIN_PORT", "8080"))
    testing_port = int(os.getenv("HAA_TESTING_PORT", "8081"))

    controller = ServerController(cfg, main_port=main_port, testing_port=testing_port)

    def _handle_signal(_signum, _frame):
        controller.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    controller.start()
    print(f"main API listening on :{main_port}")
    print(f"testing API listening on :{testing_port}")

    try:
        while any(item.thread.is_alive() for item in controller.threads):
            time.sleep(0.2)
    finally:
        controller.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
