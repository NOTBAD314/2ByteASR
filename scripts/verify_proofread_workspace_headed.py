"""Proofreading workspace on the normal app entry (private desktop, owned copies).

Copies the project, its seek cache (hard links for proxies), the user's
glossary file and the recognition timeline audio into a fresh tmp folder;
the user's own project, glossary and settings are only read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--seek-cache", type=Path, required=True)
    parser.add_argument("--glossary", type=Path, required=True)
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / "tmp"):
        raise ValueError("Fresh repository tmp required")
    out.mkdir(parents=True)
    data = args.project.read_bytes()
    glossary = args.glossary.read_bytes()
    (out / "project.2byteproj").write_bytes(data)
    for source in args.seek_cache.resolve().rglob("*"):
        if not source.is_file() or source.suffix == ".lock":
            continue
        target = out / "seek" / source.relative_to(args.seek_cache.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in {".mkv", ".mp4"}:
            os.link(source, target)
        else:
            shutil.copy2(source, target)
    profile_data = out / "profile" / "local" / "2ByteASR"
    profile_data.mkdir(parents=True)
    (profile_data / "learned_game_terms.json").write_bytes(glossary)
    shutil.copy2(args.reference_wav, out / "reference.wav")
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out / "profile"), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_ACCEPTANCE_SCENARIO="proofread-workspace",
               TWOBYTEASR_STARTUP_PROJECT=str(out / "project.2byteproj"), TWOBYTEASR_STARTUP_OPEN_STUDIO="1",
               TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / "seek"),
               TWOBYTEASR_AUDIT_REFERENCE_WAV=str(out / "reference.wav"),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", QT_QPA_PLATFORM="windows",
               PYTHONUTF8="1")
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    if args.exe and args.exe.resolve() == ROOT / "2ByteASR.exe":
        command = [sys.executable, str(ROOT / "scripts/verify_desktop_entry_bridge.py"), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / "process", timeout=900)
    result = json.loads((out / "result.json").read_text("utf8")) if (out / "result.json").exists() else {}
    result.update(exit_code=code, original_project_unchanged=args.project.read_bytes() == data,
                  original_glossary_unchanged=args.glossary.read_bytes() == glossary,
                  original_sha256=hashlib.sha256(data).hexdigest())
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps(dict(passed=result.get("passed"), checks=len(result.get("checks", [])),
                          failed=[x for x in result.get("checks", []) if not x["passed"]], error=result.get("error"),
                          previews=[(p.get("label"), p.get("ncc_vs_recognized_audio")) for p in result.get("previews", [])],
                          exit=code), ensure_ascii=False, indent=1))
    return 0 if (result.get("passed") and result.get("gui_shutdown") and code == 0
                 and result["original_project_unchanged"] and result["original_glossary_unchanged"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
