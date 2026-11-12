"""Launch the fixed handoff project through source, frozen or original entry."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
    args=parser.parse_args();output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):raise ValueError('Choose fresh source/tmp output')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,save_project
    save_project(load_project(args.project),output/'input.2byteproj')
    import shutil
    shutil.copyfile(ROOT/'tests/fixtures/grouping_contract/luoke_ace6.json',output/'fixture.json')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='handoff-ai-priority',TWOBYTEASR_STARTUP_PROJECT=str(output/'input.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=output,timeout=300,receipt=output/'result.json')
    result=json.loads((output/'result.json').read_text('utf-8'))
    print(json.dumps(dict(passed=result.get('passed'),exit_code=code,checks=len(result.get('checks',[])),error=result.get('error')),ensure_ascii=False))
    return code if code else 0 if result.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
