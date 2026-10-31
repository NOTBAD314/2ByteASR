"""Normal-entry copied-project verification; no provider requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--baseline-source',type=Path)
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--profile',action='store_true')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Choose a fresh repository tmp directory')
    out.mkdir(parents=True)
    source=args.project.resolve();project=out/'project.2byteproj'
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copy2(source,project)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='review-editor',TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    if args.baseline_source:
        env.update(REVIEW_EDITOR_BASELINE='1',REVIEW_EDITOR_BASELINE_SOURCE=str(args.baseline_source.resolve()))
    if args.profile:env['REVIEW_EDITOR_PROFILE']='1'
    entry=root/'scripts/review_editor_entry.py'
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(entry)]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=480,
                        **({'desktop_name':'Default'} if args.visible else {}))
    path=out/'result.json'
    result=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    result.update(process_exit=code,source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==original)
    import psutil
    workers=result.get('qc_workers') or [(result.get('qc_worker_before_close') or {}).get('pid')]
    for worker in workers:
        if not worker:continue
        try:psutil.Process(worker).wait(10)
        except psutil.NoSuchProcess:pass
        except psutil.TimeoutExpired:result['worker_orphan']=worker
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and result['source_unchanged'] and code==0 and not result.get('worker_orphan'))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','process_exit','gui_shutdown','error','worker_orphan')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
