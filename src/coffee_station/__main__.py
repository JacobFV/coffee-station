from __future__ import annotations

import argparse
import threading
import time
import webbrowser

from .desktop import desktop_launch_config, run_desktop, run_server
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Coffee Station.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--server", action="store_true", help="Run only the local HTTP server; do not open a desktop window.")
    parser.add_argument("--browser", action="store_true", help="Run the local server and open the system browser.")
    parser.add_argument("--no-browser", action="store_true", help="Deprecated alias for --server.")
    args = parser.parse_args()

    settings = Settings()
    if args.browser:
        launch = desktop_launch_config(settings, host=args.host, port=args.port)
        threading.Thread(target=_open_browser, args=(launch.url,), daemon=True).start()
        run_server(settings, host=launch.host, port=launch.port)
    elif args.server or args.no_browser:
        run_server(settings, host=args.host, port=args.port)
    else:
        run_desktop(settings, host=args.host, port=args.port)


def _open_browser(url: str) -> None:
    time.sleep(1.0)
    webbrowser.open(url)


if __name__ == "__main__":
    main()
