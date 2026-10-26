"""Repeatable source/frozen preview audit in an isolated Windows desktop."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--project',required=True,type=Path)
    p.add_argument('--other-project',type=Path)
    p.add_argument('--baseline-source',type=Path)
    p.add_argument('--exe',type=Path)
    p.add_argument('--mode',choices=('all','lifecycle','interaction','speed'),default='all')
    p.add_argument('--cycles',type=int,default=10)
    p.add_argument('--profile',action='store_true')
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('Use a fresh directory under this checkout/tmp')
    out.mkdir(parents=True)
    for dest,src in [('project.2byteproj',a.project),('entry.2byteproj',a.project),('other.2byteproj',a.other_project)]:
        if src:shutil.copy2(src,out/dest)
    source_sha=hashlib.sha256(a.project.read_bytes()).hexdigest()
    for font in (ROOT/'assets/fonts').glob('*'):
        if font.suffix.lower() in ('.otf','.ttf','.ttc'):
            target=out/'local/Microsoft/Windows/Fonts'/font.name
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(font,target)
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='preview-lifecycle-performance',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_STARTUP_PROJECT=str(out/'entry.2byteproj'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONUNBUFFERED='1',
        TWOBYTEASR_PREVIEW_MODE=a.mode,TWOBYTEASR_PREVIEW_CYCLES=str(a.cycles),
        TWOBYTEASR_PREVIEW_PROFILE='1' if a.profile else '0',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):env.pop(key,None)
    if a.exe:
        command=[str(a.exe.resolve())]
    elif a.baseline_source:
        # Instrumentation only; imports the untouched baseline modules and its normal entry.
        driver=out/'source_driver.py'
        driver.write_text('''def main():
    import importlib.util,os,sys
    from pathlib import Path
    source=Path(os.environ['TWOBYTEASR_BASELINE_SOURCE'])
    sys.path.insert(0,str(source));sys.path.insert(1,str(source/'scripts'))
    from twobyteasr.acceptance import studio_acceptance_audit
    spec=importlib.util.spec_from_file_location('twobyteasr.acceptance.preview_repair_audit',os.environ['TWOBYTEASR_PREVIEW_AUDIT_MODULE'])
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    studio_acceptance_audit.start_acceptance=lambda window:module.start(window,studio_acceptance_audit.audit_directory())
    import quick_start
    return quick_start.main()
if __name__=='__main__':raise SystemExit(main())
''','utf8')
        env.update(TWOBYTEASR_BASELINE_SOURCE=str(a.baseline_source.resolve()),
            TWOBYTEASR_PREVIEW_AUDIT_MODULE=str(ROOT/'twobyteasr/acceptance/preview_repair_audit.py'),
            TWOBYTEASR_ACCEPTANCE_SCENARIO='workbench-performance')
        command=[sys.executable,'-X','utf8',str(driver)]
    else:command=[sys.executable,'-B',str(ROOT/'quick_start.py')]
    sys.path.insert(0,str(ROOT/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    gpu=None
    try:
        executable=shutil.which('nvidia-smi')
        if executable:
            gpu=subprocess.Popen([executable,'--query-gpu=timestamp,utilization.gpu,utilization.decoder,memory.used',
                '--format=csv,noheader,nounits','-lms','500','-f',str(out/'gpu.csv')],stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        entry_cwd=(a.baseline_source or ROOT).resolve() if not a.exe else ROOT
        code=run_on_desktop(command,cwd=entry_cwd,env=env,output=out/'process',timeout=900)
    finally:
        if gpu is not None:gpu.terminate();gpu.wait(10)
    path=out/'result.json';result=json.loads(path.read_text('utf8')) if path.exists() else {}
    result.update(exit_code=code,source_unchanged=hashlib.sha256(a.project.read_bytes()).hexdigest()==source_sha,
                  input_sha256=source_sha,source_entry=str(a.baseline_source or ROOT),
                  gpu_measurement='whole NVIDIA GPU, sampled every 500ms; includes other desktop applications')
    if (out/'error.txt').exists():result.setdefault('errors',[]).append((out/'error.txt').read_text('utf8'))
    result['functional_pass']=bool(code==0 and result.get('finished') and result.get('passed') and result['source_unchanged'] and not result.get('errors'))
    result['measurement_valid']=False
    result['performance_pass']='UNVERIFIED'
    result['performance_scope']='Lifecycle/control audit; IPC observations and Qt heartbeats do not prove system display cadence'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps(dict(output=str(out),exit_code=code,finished=result.get('finished'),passed=result.get('passed'),errors=result.get('errors'),checks=len(result.get('checks',[]))),ensure_ascii=False))
    return 0 if code==0 and result.get('finished') and result.get('passed') and result['source_unchanged'] and not result.get('errors') else 1

if __name__=='__main__':raise SystemExit(main())
