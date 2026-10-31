"""Normal Windows entry: design B completion bar, summaries and preview fill.

    python -X utf8 scripts/verify_completion_todo_headed.py --output tmp/<new folder> [--exe <candidate>/2ByteASR.exe] [--visible]

Generated isolated tasks only; no user project, no provider request.
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
    parser.add_argument("--screen-scale-factor", type=float,
                        help="Qt scale for this verification process only; use 1 for a native 1300px-tall window")
    parser.add_argument("--tall-only", action="store_true", help="Verify the 1460×1300 layout separately from the native narrow-window pass")
    parser.add_argument("--visible", action="store_true", help="Run the same automatic checks on the active desktop")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root / "tmp"):
        parser.error("Choose a fresh output directory under repository tmp")
    output.mkdir(parents=True)
    # The tasks are generated here; the harness requires its own project file.
    from twobyteasr.acceptance.completion_todo_audit import build_tasks
    busy, _quiet = build_tasks(output)
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_STARTUP_PROJECT=str(busy[1]),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="completion-todo", TWOBYTEASR_INVOKER_CWD=str(root),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", TWOBYTEASR_DIAGNOSTIC_NO_PLAYER="1",
               QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    if args.screen_scale_factor is not None:
        if args.screen_scale_factor <= 0:
            parser.error("Screen scale factor must be positive")
        env.update(QT_ENABLE_HIGHDPI_SCALING="0", QT_FONT_DPI="96",
                   QT_SCALE_FACTOR=str(args.screen_scale_factor), QT_SCALE_FACTOR_ROUNDING_POLICY="PassThrough")
    if args.tall_only:
        env["TWOBYTEASR_COMPLETION_TODO_TALL_ONLY"] = "1"
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
    result["screen_scale_factor"] = env.get("QT_SCALE_FACTOR")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = code == 0 and result.get("passed") and result.get("gui_shutdown")
    print(json.dumps({"passed": bool(passed), "checks": len(result.get("checks", [])),
                      "error": result.get("error"), "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
