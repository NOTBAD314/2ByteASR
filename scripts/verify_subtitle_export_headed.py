"""Real Studio export dialog and stand-alone rescue window on a private desktop."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def worker(output):
    from twobyteasr.acceptance.subtitle_export_audit import run
    return run(output)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--rescue-exe",type=Path)
    parser.add_argument("--rescue-source",action="store_true")
    parser.add_argument("--app-exe",type=Path)
    args=parser.parse_args();output=args.output.resolve()
    if args.worker:return worker(output)
    if output.exists():parser.error("use a fresh directory")
    env=os.environ.copy();env["QT_QPA_PLATFORM"]="windows"
    # The full application's acceptance guard requires app data beneath the
    # audit directory. Stand-alone rescue owns an exclusive output directory.
    env["TWOBYTEASR_TEST_ROOT"]=str(output if args.app_exe else output.with_name(output.name+"-profile"))
    from isolated_windows_desktop import run_on_desktop
    if args.rescue_exe:
        command=[str(args.rescue_exe.resolve()),"--ui-audit",str(output)]
    elif args.rescue_source:
        command=[sys.executable,"-X","utf8",str(ROOT/"scripts/subtitle_rescue.py"),"--ui-audit",str(output)]
    elif args.app_exe:
        output.mkdir(parents=True)
        os.environ["TWOBYTEASR_TEST_ROOT"]=env["TWOBYTEASR_TEST_ROOT"]
        from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
        fixture=output/"blank.2byteproj"
        save_project(SubtitleProject(StudioMedia("",duration_ms=0)),fixture)
        env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO="subtitle-export-rescue",
                   TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
                   TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1", HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
        command=[str(args.app_exe.resolve())]
    else:
        output.mkdir(parents=True)
        command=[sys.executable,"-X","utf8",str(Path(__file__).resolve()),"--worker","--output",str(output)]
    # The process log must not pre-create the self-test's exclusive directory.
    code=run_on_desktop(command,cwd=ROOT,env=env,output=output.with_name(output.name+"-process"),timeout=60)
    if args.app_exe:
        result=json.loads((output/"result.json").read_text(encoding="utf-8")) if (output/"result.json").exists() else {}
        if result.get("entry")!="frozen" or result.get("failed")!=0 or result.get("passed",0)<9:
            code=1
    print(json.dumps({"exit_code":code,"output":str(output)}))
    return code


if __name__=="__main__":raise SystemExit(main())
