"""Run the actual range-recovery flow with a copied project on a private desktop."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,sys,time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path);p.add_argument('--mode',choices=('restore','verify'),default='restore')
    p.add_argument('--require-translation',action='store_true')
    p.add_argument('--frame-export',action='store_true')
    p.add_argument('--models',type=Path,required=True);p.add_argument('--main-python',type=Path,required=True)
    p.add_argument('--runtime-root',type=Path,help='Read-only reference to existing managed runtimes for frozen QA')
    args=p.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):raise ValueError('Use a new output under source tmp/')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    # Test isolation intentionally ignores model roots outside its profile.
    # Expose installed weights through read-only directory references in this
    # owned profile; neither copy nor modify the real model files.
    import subprocess
    runtime_receipt=None
    if args.runtime_root:
        from twobyteasr.runtime_paths import managed_runtime_root
        target=args.runtime_root.resolve();link=Path(managed_runtime_root())
        if not (target/'registry.json').is_file():raise ValueError('Managed runtime registry is required')
        if not link.is_relative_to(out) or link.is_symlink():raise ValueError('Use only this audit profile runtime path')
        if link.exists():link.rmdir()  # only an empty, owned directory
        link.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(target)],check=True,capture_output=True)
        registry=target/'registry.json'
        runtime_receipt=dict(root=str(target),registry_sha256=hashlib.sha256(registry.read_bytes()).hexdigest())
        (out/'read-only-runtime.json').write_text(json.dumps(runtime_receipt),encoding='utf8')
    for name in ('Qwen3-ASR-1.7B','Qwen3-ForcedAligner-0.6B'):
        target=(args.models/name).resolve();link=out/'profile/models'/name
        if target.is_dir():
            link.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(target)],check=True,capture_output=True)
    from twobyteasr.projects.studio_project import load_project,save_project
    from twobyteasr.storage.settings import DEFAULT_SETTINGS,project_settings_path
    project=load_project(args.project);report=Path(project.report_path)
    if report.is_file():
        shutil.copy2(report,out/'original-report.json');project.report_path=str(out/'original-report.json')
    fixture=save_project(project,out/'projects/fixture.2byteproj')
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['models'].update(primary_asr_backend='qwen_local',qwen_asr_backend='off',firered_asr_backend='qwen_aligner')
    settings['switches'].update(enable_ai_polish=False,use_ai_grouping=False,unified_glm_processing=False)
    settings['subtitle_language']={'recognition_language':'it','output':'original','translation_script':'zh-Hans'}
    config=project_settings_path();config.parent.mkdir(parents=True,exist_ok=True);config.write_text(json.dumps(settings),encoding='utf8')
    (out/'audit-config.json').write_text(json.dumps(dict(project=str(fixture),model_root=str(args.models.resolve()),
        python=str(args.main_python.resolve()),mode=args.mode,require_translation=args.require_translation,
        frame_export=args.frame_export,timeout=700)),encoding='utf8')
    env={k:v for k,v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='language-range-recovery',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    env['TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY']='1'
    from isolated_windows_desktop import run_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [str(args.main_python.resolve()),'-B',str(root/'quick_start.py')]
    code=run_on_desktop(cmd,cwd=root,env=env,output=out/'process',timeout=760)
    result={};deadline=time.monotonic()+740
    while time.monotonic()<deadline:
        try:
            result=json.loads((out/'result.json').read_text('utf8'))
            if result.get('gui_shutdown'):break
        except (OSError,ValueError):pass
        time.sleep(.2)
    import psutil
    pid=result.get('pid')
    if pid and psutil.pid_exists(pid):
        try:
            child_exit=psutil.Process(pid).wait(25)
            if child_exit!=0:result.update(passed=False,error='Owned GUI exited with '+str(child_exit))
        except psutil.NoSuchProcess:pass
        except psutil.TimeoutExpired:result.update(passed=False,error='Owned GUI did not exit after its close receipt')
    if runtime_receipt and hashlib.sha256(registry.read_bytes()).hexdigest()!=runtime_receipt['registry_sha256']:
        raise RuntimeError('Read-only runtime registry changed during this audit; no restoration attempted')
    print(json.dumps(dict(exit=code,passed=result.get('passed'),phase=result.get('phase'),error=result.get('error','')[-1200:])))
    return 0 if code==0 and result.get('passed') and result.get('gui_shutdown') else 1


if __name__=='__main__':raise SystemExit(main())
