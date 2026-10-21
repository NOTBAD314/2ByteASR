# SPDX-License-Identifier: GPL-3.0-only
"""Run the real in-app update flow of an installed EXE against the local QA feed.

    python -B scripts/verify_update_flow.py --profile tmp/release-065/qa-upgrade --feed tmp/release-065/qa-feed \
        --mode drop-once --plan '{"busy_worker": true, "dirty_project": true}' --expect 0.6.6-qa.1 --label c-update

The profile comes from ``verify_release_install.py``.  The QA feed is served
on 127.0.0.1:8765 only, with channel ``qa-local``; nothing is published.  The
program is started on a private desktop; after it hands over, this script
waits for the updater and the restarted program, then checks the install
against its component list, the preserved files, the user data and models,
and the feed server log (which archives were actually downloaded).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from verify_release_install import isolated_env, profile_paths, tree_manifest  # noqa: E402


def processes_inside(folder: Path) -> list[str]:
    import psutil
    prefix = str(folder.resolve()).lower() + os.sep
    found = []
    for process in psutil.process_iter(["pid", "exe"]):
        exe = (process.info.get("exe") or "").lower()
        if exe.startswith(prefix):
            found.append(f"{Path(exe).name}#{process.info['pid']}")
    return found


def verify_install(install: Path) -> dict:
    from twobyteasr.app.update_manifest import (COMPONENT_ORDER, COMPONENTS_FILENAME, PRESERVED_FILES,
                                            entries_from_record, file_sha256, load_installed_manifest)
    manifest = load_installed_manifest(install)
    problems = []
    checked = 0
    for name in COMPONENT_ORDER:
        for entry in entries_from_record(manifest["components"][name]):
            path = install / entry.path
            checked += 1
            if not path.is_file() or path.stat().st_size != entry.size or file_sha256(path) != entry.sha256:
                problems.append(entry.path)
    return {"version": manifest["version"], "files_checked": checked, "mismatched": problems[:50],
            "mismatch_count": len(problems), "preserved_present": {p: (install / p).is_file() for p in PRESERVED_FILES},
            "backup_dir_left": (install / ".update-backup").exists() and any((install / ".update-backup").iterdir()),
            "journal_left": (install / ".update-state" / "journal.txt").exists(),
            "components_file": (install / COMPONENTS_FILENAME).is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--feed", required=True)
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--plan", default="{}")
    parser.add_argument("--expect", default="")
    parser.add_argument("--label", required=True)
    parser.add_argument("--media", default=str(ROOT / "tmp" / "release-065" / "media" / "chinese-local-qa.mp4"))
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    paths = profile_paths(Path(args.profile))
    install, root = paths["install"], paths["root"]
    evidence = paths["evidence"] / f"update-{args.label}"
    if evidence.exists():
        raise SystemExit(f"exists: {evidence}")
    evidence.mkdir(parents=True)
    import qa_update_feed
    handler = qa_update_feed.Handler
    handler.root = Path(args.feed).resolve()
    handler.mode = args.mode
    handler.log_path = evidence / "feed-requests.jsonl"
    handler.dropped = set()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, StudioCue, save_project
        media = root / "update-test-media" / Path(args.media).name
        media.parent.mkdir(parents=True, exist_ok=True)
        if not media.exists():
            shutil.copy2(args.media, media)
        project = save_project(SubtitleProject(media=StudioMedia(path=str(media), duration_ms=11000),
                                               cues=[StudioCue("c1", 0, 2500, "今天测试兔白字幕。")]),
                               root / "update-test-media" / f"{args.label}.2byteproj")
        for stale in list(root.glob("update-flow-*.json")) + list(root.glob("update-offer-*.png")):
            stale.unlink()
        before_install = tree_manifest(install, hash_limit=None)
        before_models = tree_manifest(paths["models"], hash_limit=0)
        before_runtimes = tree_manifest(paths["data"] / "runtimes", hash_limit=0)
        state = paths["data"] / "updates"
        last_result = state / "last-result.json"
        result_mtime = last_result.stat().st_mtime if last_result.exists() else 0
        env = isolated_env(paths)
        env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(root), TWOBYTEASR_ACCEPTANCE_SCENARIO="update-flow",
                   TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_STARTUP_PROJECT=str(project),
                   TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows",
                   TWOBYTEASR_UPDATE_FEED="http://127.0.0.1:8765/2ByteASR-update.json",
                   TWOBYTEASR_UPDATE_CHANNEL="qa-local", UPDATE_FLOW_PLAN=args.plan, UPDATE_FLOW_EXPECT=args.expect,
                   NO_PROXY="127.0.0.1,localhost")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env.pop(key, None)
        from isolated_windows_desktop import run_on_desktop
        started = time.time()
        code = run_on_desktop([str(install / "2ByteASR.exe")], cwd=install, env=env, output=evidence / "process",
                              timeout=args.timeout)
        first_exit = time.time()
        # The updater (copied outside the install folder) and the restarted program may still run.
        deadline = time.monotonic() + args.timeout
        quiet_since = None
        while time.monotonic() < deadline:
            busy = processes_inside(install) + processes_inside(state)
            if busy:
                quiet_since = None
            else:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since > 5:
                    break
            time.sleep(1)
        flows = {p.name: json.loads(p.read_text("utf-8")) for p in root.glob("update-flow-*.json")}
        helper = json.loads(last_result.read_text("utf-8-sig")) if last_result.exists() \
            and last_result.stat().st_mtime > result_mtime else None
        after_install = tree_manifest(install, hash_limit=None)
        changed = sorted(k for k in set(before_install) | set(after_install)
                         if before_install.get(k, {}).get("sha256") != after_install.get(k, {}).get("sha256"))
        requests = [json.loads(line) for line in (evidence / "feed-requests.jsonl").read_text("utf-8").splitlines()] \
            if (evidence / "feed-requests.jsonl").exists() else []
        report = {
            "label": args.label, "mode": args.mode, "plan": json.loads(args.plan), "expect": args.expect,
            "first_process_exit": code, "first_process_seconds": round(first_exit - started, 1),
            "total_seconds": round(time.time() - started, 1), "helper_result": helper,
            "flows": {k: {"status": v.get("status"), "steps": [s["name"] for s in v.get("steps", [])],
                          "error": (v.get("error") or "")[:500]} for k, v in flows.items()},
            "install_changed_paths": [p for p in changed if not p.startswith((".update-state/", "__pycache__/"))
                                      and "/__pycache__/" not in p][:200],
            "install_check": verify_install(install),
            "models_unchanged": before_models == tree_manifest(paths["models"], hash_limit=0),
            "runtimes_unchanged": before_runtimes == tree_manifest(paths["data"] / "runtimes", hash_limit=0),
            "feed_requests": [{k: r.get(k) for k in ("path", "status", "range", "bytes", "cut")} for r in requests],
            "downloaded_bytes": sum(int(r.get("bytes") or 0) if r.get("cut") is None else int(r["cut"])
                                    for r in requests if r.get("status") in (200, 206)),
        }
        for name in flows:
            shutil.copy2(root / name, evidence / name)
        for png in root.glob("update-offer-*.png"):
            shutil.copy2(png, evidence / png.name)
        (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("feed_requests",)}, ensure_ascii=False,
                         indent=1)[:6000])
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
