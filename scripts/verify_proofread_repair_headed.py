"""Normal-entry, private-desktop proofreading and translation export acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--translated-project", type=Path)
    parser.add_argument("--partial-project", type=Path)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / "tmp"):
        parser.error("use a fresh directory within repository tmp")
    out.mkdir(parents=True)
    source = args.project.resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copy2(source, out / "work.2byteproj")
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out / "profile"), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO="proofread-repair", TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_STARTUP_TRACE=str(out / "startup.jsonl"), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
        TWOBYTEASR_STARTUP_PROJECT=str(out / "entry.2byteproj"), QT_QPA_PLATFORM="windows", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(out / "profile")
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    save_project(SubtitleProject(StudioMedia("")), out / "entry.2byteproj")
    if args.baseline:
        baseline = args.baseline.resolve()
        if not baseline.is_relative_to(ROOT / "tmp"):
            parser.error("baseline must be an owned source snapshot under tmp")
        env["TWOBYTEASR_PROOFREAD_BASELINE"] = str(baseline)
    if args.profile:
        env["TWOBYTEASR_PROOFREAD_PROFILE"] = "1"
    protected = {}
    for argument, key, name in ((args.translated_project, 'TWOBYTEASR_QA_TRANSLATED_PROJECT', 'complete-translation.2byteproj'),
                                (args.partial_project, 'TWOBYTEASR_QA_PARTIAL_PROJECT', 'partial-translation.2byteproj')):
        if argument:
            path = argument.resolve()
            protected[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            shutil.copy2(path, out / name)
            env[key] = str(out / name)
    if args.glossary:
        dest = out / "profile/local/2ByteASR/learned_game_terms.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.glossary, dest)
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-B", str(ROOT / "quick_start.py")]
    if args.exe and (args.exe.resolve().parent / "dist/2ByteASR/2ByteASR.exe").is_file():
        command = [sys.executable, str(ROOT / "scripts/verify_desktop_entry_bridge.py"), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=ROOT,
                          env=env, output=out / "process", timeout=420)
    path = out / "result.json"
    result = json.loads(path.read_text("utf-8")) if path.exists() else {}
    result.update(exit_code=code, original_unchanged=hashlib.sha256(source.read_bytes()).hexdigest() == before)
    result['translation_inputs_unchanged'] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == value for p,value in protected.items())
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: result.get(k) for k in ("passed", "error", "exit_code", "original_unchanged", "samples")},
                     ensure_ascii=False, indent=2))
    return 0 if code == 0 and result.get("passed") and result["original_unchanged"] and result['translation_inputs_unchanged'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
