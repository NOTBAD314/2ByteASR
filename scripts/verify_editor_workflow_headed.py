"""Run offline full editor workflow on a private Windows desktop.

Uses the ordinary application entry for both source and --exe. Output must be
a fresh repository tmp directory. No real media, provider calls or user settings.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to((root / "tmp").resolve()):
        parser.error("--output must be inside repository tmp")
    if out.exists():
        parser.error("--output must identify a fresh evidence directory")
    if args.exe and not args.exe.resolve().is_file():
        parser.error("--exe must identify an existing executable")
    out.mkdir(parents=True)
    # Keep even the launch fixture's Qt/settings initialization inside tmp.
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = save_project(SubtitleProject(media=StudioMedia(path="", duration_ms=0)),
                           out / "entry.2byteproj")
    env = os.environ.copy()
    env.update(
        TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO="editor-workflow",
        TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_DIAGNOSTIC_NO_PLAYER="1",
        QT_QPA_PLATFORM="windows", PYTHONUTF8="1",
    )
    command = ([str(args.exe.resolve())] if args.exe else
               [sys.executable, "-B", str(root / "quick_start.py")])
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=root, env=env, output=out / "process", timeout=150)

    def read_result():
        try:
            return json.loads((out / "result.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    result = read_result()
    deadline = time.monotonic() + 45
    while code == 0 and not result.get("gui_shutdown") and time.monotonic() < deadline:
        time.sleep(.2)
        result = read_result()
    if result.get("pid"):
        import psutil
        try:
            child_code = psutil.Process(result["pid"]).wait(timeout=20)
            if child_code not in (0, None):
                code = child_code
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            code = 1
    passed = code == 0 and result.get("passed") and result.get("shutdown") and result.get("gui_shutdown")
    print(json.dumps({
        "output": str(out), "exit_code": code, "passed": bool(passed),
        "checks": len(result.get("checks", [])),
        "failed_checks": [row for row in result.get("checks", []) if not row["passed"]],
        "cases": [row["name"] for row in result.get("cases", [])],
        "exports": len(result.get("artifacts", [])), "error": result.get("error"),
    }, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
