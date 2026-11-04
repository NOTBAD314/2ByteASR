"""Normal headed entry, isolated profile, retained real progress and subtitle exports."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--worker-log',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];output=args.output.resolve()
    if output.exists() or not output.is_relative_to(root/'tmp'):raise ValueError('Choose fresh tmp output')
    output.mkdir(parents=True)
    project=output/'retained.2byteproj';shutil.copyfile(args.project,project)
    log=output/'worker.log';shutil.copyfile(args.worker_log,log)
    (output/'input.json').write_text(json.dumps(dict(project=str(project),worker_log=str(log))),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(output),TWOBYTEASR_STARTUP_TRACE=str(output/'startup.jsonl'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='moss-full-context',
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    sys.path.insert(0,str(root))
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=output/'process',timeout=120)
    result_path=output/'result.json'
    result=json.loads(result_path.read_text('utf8')) if result_path.is_file() else {'passed':False,'error':'No GUI receipt'}
    result['process_exit']=code
    result['passed']=bool(result.get('passed') and code==0)
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
