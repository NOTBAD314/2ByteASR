"""Normal Windows entry: 兔白处理 bubble, window, local fixes, undo and restore.

    python -X utf8 scripts/verify_completion_ai_repair_headed.py --output tmp/<new folder> [--exe <candidate>/2ByteASR.exe] [--visible]

Generated isolated task only; no user project, no provider request.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--visible", action="store_true", help="Run the same automatic checks on the active desktop")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root / "tmp"):
        parser.error("Choose a fresh output directory under repository tmp")
    output.mkdir(parents=True)
    from twobyteasr.acceptance.completion_ai_repair_audit import build_task
    busy = build_task(output)
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_STARTUP_PROJECT=str(busy[1]),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="completion-ai-repair", TWOBYTEASR_INVOKER_CWD=str(root),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_DIAGNOSTIC_NO_PLAYER="1",
               QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(root / "quick_start.py")]
    if args.visible:
        code = subprocess.run(command, cwd=root, env=env, creationflags=subprocess.CREATE_NO_WINDOW,
                              stdout=(output / "stdout.log").open("wb"), stderr=(output / "stderr.log").open("wb"),
                              timeout=240).returncode
    else:
        code = run_on_desktop(command, cwd=root, env=env, output=output / "process", timeout=240)
    result_path = output / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    result["process_exit"] = code
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = code == 0 and result.get("passed") and result.get("gui_shutdown")
    print(json.dumps({"passed": bool(passed), "checks": len(result.get("checks", [])),
                      "error": result.get("error"), "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
