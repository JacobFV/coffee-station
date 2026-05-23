from __future__ import annotations

import argparse
import threading
import time
import webbrowser

import uvicorn

from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Coffee Station.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{host}:{port}"

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    print(f"Coffee Station running at {url}")
    uvicorn.run("coffee_station.server:create_app", factory=True, host=host, port=port, reload=False)


def _open_browser(url: str) -> None:
    time.sleep(1.0)
    webbrowser.open(url)


if __name__ == "__main__":
    main()
