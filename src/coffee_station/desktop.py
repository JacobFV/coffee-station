from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import uvicorn

from .settings import Settings

# Loopback-only renderer bridge. The embedded HTTP layer exists solely to feed
# the native pywebview window — it is never bound to a public interface and
# never exposed to the user. Treat it as in-process IPC, not a web server.
_RENDERER_HOST = "127.0.0.1"


@dataclass(frozen=True)
class RendererBridge:
    host: str
    port: int

    @property
    def loopback_url(self) -> str:
        return f"http://{self.host}:{self.port}"


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


class _RendererBackend:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.config = uvicorn.Config(
            "coffee_station.server:create_app",
            factory=True,
            host=host,
            port=port,
            reload=False,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(
            target=self.server.run,
            name="coffee-station-renderer",
            daemon=True,
        )

    def start(self, timeout_s: float = 10.0) -> None:
        self.thread.start()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("Coffee Station renderer exited before startup completed")
            time.sleep(0.05)
        raise TimeoutError(f"Coffee Station renderer did not start within {timeout_s:.1f}s")

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=5.0)


def renderer_bridge_config(settings: Settings) -> RendererBridge:
    del settings  # bridge is loopback-only; no user-tunable host/port
    return RendererBridge(host=_RENDERER_HOST, port=find_available_port(_RENDERER_HOST, 0))


def run_desktop(settings: Settings) -> None:
    try:
        import webview
    except Exception as exc:
        raise RuntimeError(
            "Coffee Station requires pywebview. Install with: pip install -e ."
        ) from exc

    bridge = renderer_bridge_config(settings)
    backend = _RendererBackend(bridge.host, bridge.port)
    backend.start()
    try:
        webview.create_window(
            "Coffee Station",
            bridge.loopback_url,
            width=1280,
            height=820,
            min_size=(960, 640),
            confirm_close=True,
        )
        webview.start()
    finally:
        backend.stop()
