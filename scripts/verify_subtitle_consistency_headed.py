"""Validate conflict handling on a private Windows desktop with isolated data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--exe",type=Path)
    parser.add_argument("--normal-entry",action="store_true")
    parser.add_argument("--child",action="store_true",help=argparse.SUPPRESS)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/"tmp"):
        raise ValueError("Evidence must stay in repository tmp")
    if args.child:
        from twobyteasr.acceptance.subtitle_consistency_audit import run
        return run(out)
    if out.exists():
        raise ValueError("Use a fresh evidence directory")
    if args.exe and not args.exe.resolve().is_file():
        parser.error("--exe must identify an existing candidate")
    out.mkdir(parents=True)
    env={**os.environ,"TWOBYTEASR_TEST_ROOT":str(out),"QT_QPA_PLATFORM":"windows",
         "PYTHONUTF8":"1","TWOBYTEASR_SKIP_FIRST_RUN_WIZARD":"1",
         "TWOBYTEASR_DIAGNOSTIC_NO_PLAYER":"1",
         "TWOBYTEASR_STARTUP_TRACE":str(out/"startup.jsonl"),
         "TWOBYTEASR_ACCEPTANCE_DIR":str(out)}
    command=[sys.executable,"-B",str(Path(__file__).resolve()),"--child","--output",str(out)]
    if args.exe or args.normal_entry:
        os.environ["TWOBYTEASR_TEST_ROOT"]=str(out)
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import StudioMedia,SubtitleProject,save_project
        fixture=save_project(SubtitleProject(media=StudioMedia(path="")),out/"entry.2byteproj")
        env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO="subtitle-consistency",
                   TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_INVOKER_CWD=str(root))
        command=[str(args.exe.resolve())] if args.exe else [sys.executable,"-B",str(root/"quick_start.py")]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/"process",timeout=100)
    result=json.loads((out/"result.json").read_text("utf8")) if (out/"result.json").exists() else {}
    print(json.dumps(dict(output=str(out),exit_code=code,passed=result.get("passed"),
                          error=result.get("error"),cases=result.get("cases")),ensure_ascii=False))
    return 0 if code==0 and result.get("passed") and result.get("shutdown") else 1


if __name__=="__main__":
    raise SystemExit(main())

