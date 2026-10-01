"""Run the real application with isolated files; also supports its frozen build."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--exe",type=Path)
    parser.add_argument("--scale",type=float,default=1.)
    parser.add_argument("--queue-result",type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/"tmp") or out.exists():
        raise ValueError("Use a new output directory under workspace tmp")
    out.mkdir(parents=True)
    shutil.copyfile(args.project,out/"fixture.2byteproj")
    if args.queue_result:
        shutil.copyfile(args.queue_result,out/"queue-result.json")
    env=os.environ.copy()
    env.update(LOCALAPPDATA=str(out/"local"),APPDATA=str(out/"roaming"),
        QT_QPA_PLATFORM="windows",QT_SCALE_FACTOR=str(args.scale/1.75),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO="timeline-delivery",
        TWOBYTEASR_STARTUP_PROJECT=str(out/"fixture.2byteproj"),TWOBYTEASR_STARTUP_OPEN_STUDIO="1",
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD="1",PYTHONIOENCODING="utf-8")
    from twobyteasr.processes import run_hidden_subprocess
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,"-B",str(root/"quick_start.py")]
    with (out/"application.log").open("wb") as log:
        result=run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=log,timeout=150,purpose="timeline delivery runtime acceptance")
    report=json.loads((out/"runtime.json").read_text(encoding="utf-8"))
    print(json.dumps({"passed":report["passed"],"error":report.get("error"),"output":str(out)},ensure_ascii=False))
    return 0 if report["passed"] and result.returncode==0 else 1


if __name__=="__main__":
    raise SystemExit(main())
