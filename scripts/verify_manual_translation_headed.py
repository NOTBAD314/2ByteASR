"""Normal Windows application entry, copied real project, manual translation acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cue", default="171")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--visible", action="store_true", help="Run the same automatic checks on the active desktop")
    parser.add_argument("--interactive", action="store_true", help="Open a copied project for native mouse/keyboard acceptance")
    parser.add_argument("--check-gaps", action="store_true", help="Also validate the short-gap handoff menu on this sample")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root / "tmp"):
        parser.error("Choose a fresh output directory under repository tmp")
    output.mkdir(parents=True)
    source = args.project.resolve()
    project = output / "DaVinci-manual-translation.2byteproj"
    shutil.copy2(source, project)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    (output / "input.json").write_text(json.dumps({"source": str(source), "sha256": original_hash,
        "cue": args.cue}, indent=2), encoding="utf-8")
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="manual-translation", TWOBYTEASR_MANUAL_TRANSLATION_CUE=args.cue,
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(root),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    env.pop("TWOBYTEASR_DIAGNOSTIC_NO_PLAYER", None)
    if args.check_gaps:
        env["TWOBYTEASR_CHECK_SHORT_GAPS"] = "1"
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(root / "quick_start.py")]
    if args.interactive:
        env["TWOBYTEASR_MANUAL_TRANSLATION_INTERACTIVE"] = "1"
        process = subprocess.Popen(command, cwd=root, env=env, creationflags=subprocess.CREATE_NO_WINDOW,
                                   stdout=(output / "stdout.log").open("wb"), stderr=(output / "stderr.log").open("wb"))
        print(json.dumps({"pid": process.pid, "output": str(output), "project": str(project)}))
        return 0
    if args.visible:
        code = subprocess.run(command, cwd=root, env=env, creationflags=subprocess.CREATE_NO_WINDOW,
                              stdout=(output / "stdout.log").open("wb"), stderr=(output / "stderr.log").open("wb"), timeout=240).returncode
    else:
        code = run_on_desktop(command, cwd=root, env=env, output=output / "process", timeout=240)
    result_path = output / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    result["process_exit"] = code
    result["source_unchanged"] = original_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = code == 0 and result.get("passed") and result.get("source_unchanged") and result.get("gui_shutdown")
    print(json.dumps({"passed": bool(passed), "checks": len(result.get("checks", [])),
                      "error": result.get("error"), "output": str(output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
