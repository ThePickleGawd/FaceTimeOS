#!/usr/bin/env python3
"""
Utility server that listens on SERVER_HOST:SERVER_PORT and prints any payload
POSTed to /api/currentaction. Handy for observing Agent-S notifications.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict


def load_dotenv() -> Dict[str, str]:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    config: Dict[str, str] = {}
    if not env_path.exists():
        return config
    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return config


ENV = {**load_dotenv(), **os.environ}
SERVER_HOST = ENV.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(ENV.get("SERVER_PORT", "8000"))


class CurrentActionHandler(BaseHTTPRequestHandler):
    server_version = "CurrentActionTest/0.1"

    def log_message(self, format: str, *args) -> None:
        # Suppress default logging; we print custom output instead.
        return

    def do_POST(self) -> None:
        if self.path != "/api/currentaction":
            self.send_error(404, "Not Found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b""
        body_text = raw_body.decode("utf-8", errors="replace")

        print("----- /api/currentaction received -----")
        print(body_text or "(empty body)")
        print("---------------------------------------", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))


def main() -> None:
    server = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), CurrentActionHandler)
    print(
        f"Listening on http://{SERVER_HOST}:{SERVER_PORT}/api/currentaction\n"
        "Press Ctrl+C to stop."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
