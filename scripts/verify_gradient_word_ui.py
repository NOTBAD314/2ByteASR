"""Normal source/frozen UI with isolated copies and continuous native video."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--scale-percent',type=int,default=100)
    parser.add_argument('--burn-word',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('New tmp directory required')
    out.mkdir(parents=True);shutil.copy2(args.project,out/'fixture.2byteproj')
    env=os.environ.copy();env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.scale_percent/175),PYTHONIOENCODING='utf-8',
        TWOBYTEASR_ACCEPTANCE_EXPECT_DPR=str(args.scale_percent/100),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='gradient-word',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    if args.burn_word:env['TWOBYTEASR_ACCEPTANCE_BURN_WORD']='1'
    from twobyteasr.processes import run_hidden_subprocess
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    with (out/'application.log').open('wb') as log:
        r=run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=log,timeout=180,purpose='gradient and word split UI verification')
    report=json.loads((out/'runtime.json').read_text(encoding='utf-8'))
    passed=report['passed'] and all(report.get('checks',{}).values()) and r.returncode==0
    print(json.dumps(dict(passed=passed,exit_code=r.returncode,error=report.get('error')),ensure_ascii=False))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
