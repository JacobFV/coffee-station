from __future__ import annotations

import argparse

from .desktop import run_desktop
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="coffee-station",
        description="Launch the Coffee Station desktop app.",
    )
    parser.parse_args()
    run_desktop(Settings())


if __name__ == "__main__":
    main()
