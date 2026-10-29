# SPDX-License-Identifier: GPL-3.0-only
"""QA-only update feed: a local "next version" built from a frozen payload, and a server.

Never published.  The QA version uses channel ``qa-local`` so an installed
stable program ignores it unless ``TWOBYTEASR_UPDATE_CHANNEL=qa-local`` and
``TWOBYTEASR_UPDATE_FEED=http://127.0.0.1:<port>/2ByteASR-update.json`` are set.

    python -B scripts/qa_update_feed.py make-build --from tmp/release-065/build-r4 --out tmp/release-065/qa-066 \
        --version 0.6.6-qa.1
    python -B scripts/release_pipeline.py feed --build tmp/release-065/qa-066 --assets tmp/release-065/qa-feed \
        --channel qa-local --base-url http://127.0.0.1:8765/ --no-copy-setup --tag v0.6.6-qa.1 \
        --previous-manifest releases/0.6.5/2ByteASR-update.json --notes-json <json>
    python -B scripts/qa_update_feed.py serve --root tmp/release-065/qa-feed --port 8765 --mode drop-once --log <jsonl>

Modes: normal (Range supported), no-range (always full 200), drop-once (first
archive request is cut off mid-way), corrupt (archives are served with one
flipped byte), missing (archives answer 404), slow-manifest (manifest held 20 s).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_build(args) -> None:
    from twobyteasr.app.update_manifest import COMPONENTS_FILENAME, build_installed_manifest, file_sha256, parse_version
    source = Path(args.source).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        raise SystemExit(f"exists: {out}")
    version = str(parse_version(args.version))
    freeze = json.loads((source / "evidence" / "freeze.json").read_text("utf-8"))
    src_payload = Path(freeze["payload"])
    payload = out / "payload" / "2ByteASR"
    # Hard links keep the 1.9 GB copy cheap; changed files are written as new files.
    for path in src_payload.rglob("*"):
        target = payload / path.relative_to(src_payload)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, target)

    def rewrite(rel, data: bytes):
        target = payload / rel
        if target.exists():
            target.unlink()  # break the hard link before writing
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    version_file = json.loads((payload / "2byteasr_version.json").read_text("utf-8-sig"))
    version_file.update(version=version, channel="qa-local")
    rewrite("2byteasr_version.json", (json.dumps(version_file, indent=2) + "\n").encode("utf-8"))
    identity = json.loads((payload / "2byteasr_build.json").read_text("utf-8"))
    identity.update(app_version=version, build_channel="qa-local-update-test")
    rewrite("2byteasr_build.json", json.dumps(identity, indent=2).encode("utf-8"))
    rewrite("docs/qa-update-marker.txt", f"QA-only update marker for {version}; never published.\n".encode())
    rewrite("licenses/QA-UPDATE-NOTE.txt", b"QA-only licence component change; never published.\n")
    removed = "CHANGELOG.md"
    (payload / removed).unlink()
    (payload / COMPONENTS_FILENAME).unlink()
    manifest = build_installed_manifest(payload, version=version, build=identity)
    (payload / COMPONENTS_FILENAME).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (out / "evidence").mkdir(parents=True)
    record = {**freeze, "version": version, "identity": identity, "payload": str(payload), "stage": None,
              "qa_only": True, "changes": {"modified": ["2byteasr_version.json", "2byteasr_build.json"],
                                           "added": ["docs/qa-update-marker.txt", "licenses/QA-UPDATE-NOTE.txt"],
                                           "removed": [removed]},
              "components": {k: {kk: vv for kk, vv in v.items() if kk != "files"}
                             for k, v in manifest["components"].items()}}
    (out / "evidence" / "freeze.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(record["components"], indent=1))


class Handler(BaseHTTPRequestHandler):
    root: Path = Path(".")
    mode = "normal"
    log_path: Path | None = None
    dropped: set = set()
    lock = threading.Lock()

    def log_message(self, *_args):
        return

    def _record(self, **data):
        if self.log_path:
            with self.lock, self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"t": time.time(), "path": self.path, **data}) + "\n")

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        name = self.path.split("?")[0].lstrip("/")
        file = (self.root / name).resolve()
        if not file.is_file() or not file.is_relative_to(self.root):
            self._record(status=404)
            self.send_error(404)
            return
        archive = name.endswith(".zip")
        if archive and self.mode == "missing":
            self._record(status=404, mode=self.mode)
            self.send_error(404)
            return
        if name.endswith(".json") and self.mode == "slow-manifest":
            self._record(status="received-holding-20s")
            time.sleep(20)
        data = file.read_bytes()
        if archive and self.mode == "corrupt":
            data = data[:100] + bytes([data[100] ^ 0xFF]) + data[101:]
        start = 0
        header = self.headers.get("Range", "")
        if header.startswith("bytes=") and self.mode not in ("no-range",) and not (archive and self.mode == "corrupt"):
            start = int(header[6:].split("-")[0] or 0)
        if start >= len(data) and start:
            self._record(status=416, range=header)
            self.send_error(416)
            return
        body = data[start:]
        self.send_response(206 if start else 200)
        if start:
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.send_header("Accept-Ranges", "bytes" if self.mode != "no-range" else "none")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if head:
            return
        cut = None
        with self.lock:
            if archive and self.mode == "drop-once" and name not in self.dropped:
                self.dropped.add(name)
                cut = len(body) // 2
        self._record(status=206 if start else 200, range=header or None, bytes=len(body), cut=cut)
        try:
            self.wfile.write(body[:cut] if cut is not None else body)
            if cut is not None:
                self.wfile.flush()
                self.connection.shutdown(2)
        except (ConnectionError, OSError):
            pass


def serve(args) -> None:
    Handler.root = Path(args.root).resolve()
    Handler.mode = args.mode
    Handler.log_path = Path(args.log).resolve() if args.log else None
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {Handler.root} on 127.0.0.1:{args.port} mode={args.mode}", flush=True)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("make-build"); p.add_argument("--from", dest="source", required=True)
    p.add_argument("--out", required=True); p.add_argument("--version", required=True); p.set_defaults(func=make_build)
    p = sub.add_parser("serve"); p.add_argument("--root", required=True); p.add_argument("--port", type=int, default=8765)
    p.add_argument("--mode", default="normal", choices=["normal", "no-range", "drop-once", "corrupt", "missing",
                                                        "slow-manifest"])
    p.add_argument("--log"); p.set_defaults(func=serve)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
