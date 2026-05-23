from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import uvicorn

from .settings import Settings


@dataclass(frozen=True)
class DesktopLaunch:
    host: str
    port: int
    url: str


def find_available_port(host: str, preferred: int) -> int:
    if preferred <= 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((host, preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class EmbeddedServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.config = uvicorn.Config(
            "coffee_station.server:create_app",
            factory=True,
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, name="coffee-station-server", daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, timeout_s: float = 10.0) -> None:
        self.thread.start()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("Coffee Station server exited before startup completed")
            time.sleep(0.05)
        raise TimeoutError(f"Coffee Station server did not start within {timeout_s:.1f}s")

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=5.0)


def desktop_launch_config(settings: Settings, host: str | None = None, port: int | None = None) -> DesktopLaunch:
    resolved_host = host or settings.host
    resolved_port = find_available_port(resolved_host, port or settings.port)
    return DesktopLaunch(host=resolved_host, port=resolved_port, url=f"http://{resolved_host}:{resolved_port}")


def run_desktop(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    try:
        import webview
    except Exception as exc:
        raise RuntimeError("Desktop mode requires pywebview. Install with: pip install -e .") from exc

    launch = desktop_launch_config(settings, host=host, port=port)
    server = EmbeddedServer(launch.host, launch.port)
    server.start()
    print(f"Coffee Station desktop running at {launch.url}")
    try:
        webview.create_window(
            "Coffee Station",
            launch.url,
            width=1280,
            height=820,
            min_size=(960, 640),
            confirm_close=True,
        )
        webview.start()
    finally:
        server.stop()


def run_server(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    launch = desktop_launch_config(settings, host=host, port=port)
    print(f"Coffee Station running at {launch.url}")
    uvicorn.run("coffee_station.server:create_app", factory=True, host=launch.host, port=launch.port, reload=False)
