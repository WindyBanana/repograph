"""Entry point for the packaged applications.

One binary serves both audiences: run it from a terminal and it is the CLI; open
it from a desktop launcher, the Dock or Explorer and it opens the UI, because a
double-clicked window that prints usage and exits is not an application.
"""

from __future__ import annotations

import os
import sys


def _launched_from_a_desktop() -> bool:
    """True when nobody is watching a terminal for output."""
    if os.environ.get("REPOGRAPH_FORCE_UI"):
        return True
    if os.environ.get("REPOGRAPH_FORCE_CLI"):
        return False
    try:
        return not (sys.stdin and sys.stdin.isatty())
    except (ValueError, AttributeError):
        return True


def main() -> int:
    if len(sys.argv) == 1 and _launched_from_a_desktop():
        from repograph_ui.server import serve

        return serve(open_browser=True)
    from repograph_cli.main import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
