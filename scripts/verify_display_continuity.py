"""Launch the real-window continuity audit on an isolated Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Choose a fresh source/tmp output.')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,save_project
    save_project(load_project(args.project),output/'input.2byteproj')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='display-continuity',TWOBYTEASR_STARTUP_PROJECT=str(output/'input.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TWOBYTEASR_TEST_ROOT=str(output/'profile'))
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=output,timeout=240,receipt=output/'result.json')
    result=json.loads((output/'result.json').read_text(encoding='utf-8'))
    result['process_exit']=code
    result['passed']=bool(result.get('passed') and code==0)
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],process_exit=code,error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
