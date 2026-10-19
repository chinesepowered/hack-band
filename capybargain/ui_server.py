"""Serve the Capy Onsen UI, plus a live feed of the newest run.

    uv run python -m capybargain.ui_server
    open http://localhost:8000/web/            replay the recorded demo run
    open http://localhost:8000/web/?live       watch the newest HQ room live, as Band records it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

from capybargain import owner, transcript

ROOT = Path(__file__).resolve().parent.parent


class LiveFeed:
    """Re-reads the newest HQ room (and its quote rooms) from Band, at most every 1.5s."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fetched_at = 0.0
        self.body = b'{"waiting": true}'

    def get(self) -> bytes:
        with self.lock:
            if time.monotonic() - self.fetched_at > 1.5:
                try:
                    self.body = json.dumps(asyncio.run(self.capture()), ensure_ascii=False).encode()
                except SystemExit:  # no HQ room yet
                    self.body = b'{"waiting": true}'
                self.fetched_at = time.monotonic()
            return self.body

    @staticmethod
    async def capture() -> dict:
        c = owner.client()
        return await transcript.capture(c, await owner.latest_hq(c))


class Handler(SimpleHTTPRequestHandler):
    live = LiveFeed()

    def do_GET(self) -> None:
        if self.path.startswith("/api/live"):
            body = self.live.get()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", "/web/")
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(ROOT)))
    print(f"🍊 Capy Onsen at http://localhost:{args.port}/web/  (live: /web/?live)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
