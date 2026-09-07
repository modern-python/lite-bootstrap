"""Minimal OTLP/HTTP sink so the exporter succeeds instead of retrying with backoff.

A dead endpoint would leave the exporter thread spinning on retries, which shows up as noise in
the request-path measurement. Started and stopped by `run.py` / `run_http.py` for the stack suite.
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("content-type", "application/x-protobuf")
        self.send_header("content-length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence the default stderr access log."""


if __name__ == "__main__":
    port = int(sys.argv[1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
