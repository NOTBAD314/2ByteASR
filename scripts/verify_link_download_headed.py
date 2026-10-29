"""Normal Windows entry, isolated profile, real YouTube -> edit -> save/export."""
from pathlib import Path
import argparse
import json
import hashlib
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--timeout",type=int,default=360)
    parser.add_argument("--exe",type=Path,help="Validate this frozen EXE or the daily launcher")
    parser.add_argument("--review-project",type=Path)
    parser.add_argument("--multisite",action="store_true")
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(ROOT/"tmp") or out.exists():
        parser.error("Use a fresh directory under repository tmp")
    out.mkdir(parents=True)
    source_files = {}
    for path in sorted((ROOT/"twobyteasr").rglob("*.py")):
        source_files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("quick_start.py", "subtitle_core.py", "dependencies.lock.json"):
        source_files[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    (out/"source-files.json").write_text(json.dumps(dict(files=source_files,
        digest=hashlib.sha256(json.dumps(source_files,sort_keys=True).encode()).hexdigest()),indent=2),encoding="utf-8")
    os.environ["TWOBYTEASR_TEST_ROOT"]=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    entry=save_project(SubtitleProject(media=StudioMedia(path="")),out/"entry.2byteproj")
    if args.review_project:
        import shutil
        shutil.copyfile(args.review_project.resolve(),entry)
    env=os.environ.copy()
    for key in ("TWOBYTEASR_STARTUP_OPEN_STUDIO","TWOBYTEASR_STARTUP_RAISE","TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE"):
        env.pop(key,None)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO="link-download",TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(entry),TWOBYTEASR_STARTUP_TRACE=str(out/"startup.jsonl"),
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",
        QT_QPA_PLATFORM="windows",PYTHONUTF8="1",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
    if args.review_project:
        env["TWOBYTEASR_ACCEPTANCE_SCENARIO"]="link-download-review"
    if args.multisite:
        env["TWOBYTEASR_ACCEPTANCE_SCENARIO"]="link-multisite"
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable,"-B",str(ROOT/"quick_start.py")]
    code=run_on_desktop(command,cwd=ROOT,env=env,
                       output=out/"process",timeout=args.timeout)
    result=json.loads((out/"link-download.json").read_text("utf-8")) if (out/"link-download.json").exists() else {}
    print(json.dumps(dict(output=str(out),exit_code=code,passed=result.get("passed"),
        checks=len(result.get("checks",[])),error=result.get("error")),ensure_ascii=False))
    identity = result.get("identity", {})
    return 0 if code==0 and result.get("passed") and result.get("gui_shutdown") and (not args.exe or identity.get("packaged")) else 1


if __name__=="__main__":
    raise SystemExit(main())
