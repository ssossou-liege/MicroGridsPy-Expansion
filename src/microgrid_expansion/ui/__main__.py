"""Open the interface.

By default in a window of its own, which is what a developer expects of a tool; ``--browser``
falls back to the default browser, and ``--serve`` only starts the server, which is what a
test or a remote session wants.
"""
from __future__ import annotations

import argparse
import socket
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
                        help="ouvrir dans le navigateur plutôt que dans sa propre fenêtre")
    parser.add_argument("--serve", action="store_true",
                        help="démarrer le serveur seul, sans ouvrir de fenêtre")
    args = parser.parse_args(argv)

    port = args.port or _free_port()
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    if args.serve:
        print(f"interface sur {url}", flush=True)
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
        print(f"interface sur {url}", flush=True)
        webbrowser.open(url)
        thread.join()
        return 0

    import webview
    webview.create_window("MicroGrids — dimensionnement certifié", url,
                          width=1280, height=860, min_size=(1024, 700))
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
