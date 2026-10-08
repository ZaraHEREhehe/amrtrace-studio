# Minimal Z-02 API stub used only for container health verification.

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: HTTPStatus, payload: dict[str, str]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"service": "api", "status": "ok"})
            return

        if self.path == "/":
            self._send_json(
                HTTPStatus.OK,
                {"service": "amrtrace-api-stub", "status": "running"},
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        print(f"api-stub: {format % args}")


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"api-stub listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
