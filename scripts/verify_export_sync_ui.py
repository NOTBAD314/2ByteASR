"""Launch source/frozen acceptance, with persistent isolated preferences."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--duration',type=float,default=12)
    parser.add_argument('--restart',action='store_true')
    parser.add_argument('--caption-checks',action='store_true')
    parser.add_argument('--scale-percent',type=int,choices=(100,125,150),default=100)
    args=parser.parse_args()
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or (out.exists() and not args.restart):
        raise ValueError('New tmp directory required')
    out.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(args.project,out/'fixture.2byteproj')
    env=os.environ.copy()
    env.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR=str(args.scale_percent/175), TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='export-sync',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',PYTHONIOENCODING='utf-8',
        TWOBYTEASR_EXPORT_DURATION=str(args.duration),TWOBYTEASR_EXPORT_RESTART='1' if args.restart else '0')
    if args.caption_checks: env['TWOBYTEASR_CAPTION_REPAIR_AUDIT']='1'
    from twobyteasr.processes import run_hidden_subprocess
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    stop=threading.Event()
    def monitor():
        import psutil
        owner=psutil.Process()
        with (out/'resources.jsonl').open('a',encoding='utf-8') as log:
            while not stop.wait(1):
                rows=[]
                for process in owner.children(recursive=True):
                    try:rows.append(dict(pid=process.pid,name=process.name(),cpu_seconds=sum(process.cpu_times()[:2]),
                        rss=process.memory_info().rss,io=process.io_counters()._asdict()))
                    except psutil.Error:pass
                gpu=run_hidden_subprocess(['nvidia-smi','--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used',
                    '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,purpose='export resource measurement')
                log.write(json.dumps(dict(monotonic=time.monotonic(),processes=rows,gpu=gpu.stdout.strip()))+'\n');log.flush()
    observer=threading.Thread(target=monitor,daemon=True)
    observer.start()
    try:
        with (out/('restart.log' if args.restart else 'application.log')).open('wb') as log:
            result=run_hidden_subprocess(command,cwd=root,env=env,stdout=log,stderr=log,timeout=1000,purpose='export sync UI acceptance')
    finally:
        stop.set();observer.join(4)
    report=json.loads((out/('restart-runtime.json' if args.restart else 'runtime.json')).read_text(encoding='utf-8'))
    passed=report['passed'] and all(report.get('checks',{}).values()) and result.returncode==0
    if args.caption_checks:
        caption=json.loads((out/'caption-repair.json').read_text(encoding='utf-8'))
        passed=passed and caption.get('passed',False) and all(caption['checks'].values())
    print(json.dumps({'passed':passed,'error':report.get('error'),'exit_code':result.returncode},ensure_ascii=False))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
