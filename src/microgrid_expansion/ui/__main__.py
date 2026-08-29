"""Open the interface.

By default in a window of its own, which is what a developer expects of a tool; ``--browser``
falls back to the default browser, and ``--serve`` only starts the server, which is what a
test or a remote session wants.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

import uvicorn

from .server import create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--browser", action="store_true",
                        help="open in the browser rather than in a window of its own")
    parser.add_argument("--serve", action="store_true",
                        help="start the server alone, opening no window")
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    if args.serve:
        print(f"MicroGridsPy on {url}", flush=True)
        server.run()
        return 0

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):                       # the window must not open onto nothing
        if server.started:
            break
        time.sleep(0.05)

    if args.browser:
        import webbrowser
        print(f"MicroGridsPy on {url}", flush=True)
        webbrowser.open(url)
        thread.join()
        return 0

    try:
        import webview

        webview.create_window("MicroGridsPy", url,
                              width=1280, height=860, min_size=(1024, 700))
        # On Linux pywebview tries GTK first and prints a traceback when the bindings are
        # absent, which they are on a pip install. Qt is what the environment ships, so name
        # it and skip the alarming detour; elsewhere the platform's own web view is right.
        webview.start(gui="qt" if sys.platform.startswith("linux") else None)
    except Exception as exc:                       # noqa: BLE001 - reported, then worked around
        # A window needs a native web view, which Windows and macOS ship and Linux does not.
        # Falling back to the browser is better than failing: the interface is the same page
        # either way, and a developer who wanted a window would rather be told why they did
        # not get one than be left with nothing.
        print(f"no window available ({exc}); opening in the browser instead.", flush=True)
        import webbrowser

        print(f"MicroGridsPy on {url}", flush=True)
        webbrowser.open(url)
        thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
