# SPDX-License-Identifier: GPL-3.0-only
"""RELEASING.md step 10 (2026-10-18): serve chosen release files to the Baidu Netdisk web page on this PC only (127.0.0.1, random path, CORS + Chromium
Private Network Access headers for https://pan.baidu.com), so page JavaScript can hand them to Baidu's own upload input.
usage: baidu_web_upload_serve.py <port> <secret path segment> <file> [<file> ...]   (stop with Ctrl+C / kill)"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

port, secret = int(sys.argv[1]), sys.argv[2]
FILES = {Path(f).name: Path(f).resolve() for f in sys.argv[3:]}
ORIGIN = "https://pan.baidu.com"


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != secret or parts[1] not in FILES or \
                self.headers.get("Origin", ORIGIN) != ORIGIN:
            self.send_response(404)
            self.end_headers()
            return
        path = FILES[parts[1]]
        size = path.stat().st_size
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with path.open("rb") as stream:
            while True:
                block = stream.read(1 << 20)
                if not block:
                    break
                self.wfile.write(block)
        print(f"served {path.name} {size}", flush=True)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
