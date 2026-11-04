"""Run the real 6962-cue project from a protected copy, source or full EXE."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,threading,time


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--record',action='store_true')
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--loading-only',action='store_true')
    parser.add_argument('--uia',action='store_true')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--hold',action='store_true')
    parser.add_argument('--maximized',action='store_true')
    parser.add_argument('--qt-scale',default='1')
    parser.add_argument('--render-profile',action='store_true')
    parser.add_argument('--foreground-gate',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    assert out.is_relative_to(root/'tmp') and not out.exists()
    out.mkdir(parents=True)
    before=hashlib.sha256(args.project.read_bytes()).hexdigest()
    shutil.copy2(args.project,out/'project.2byteproj')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='real-long-project',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_SIZE='1440x900',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.qt_scale,PYTHONUTF8='1',
        REAL_LONG_PROJECT=str(out/'project.2byteproj'),REAL_LONG_RECORD=str(int(args.record)),
        REAL_LONG_PROFILE=str(int(args.profile)),
        REAL_LONG_LOADING_ONLY=str(int(args.loading_only)),
        REAL_LONG_HOLD=str(int(args.hold)),REAL_LONG_MAXIMIZED=str(int(args.maximized)),
        REAL_LONG_RENDER_PROFILE=str(int(args.render_profile)),
        REAL_LONG_FOREGROUND_GATE=str(int(args.foreground_gate)),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SEEK_CACHE_ROOT=str(root/'tmp/real-long-shared-seek'))
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO',None)
    original_mpv=root.parents[2]/'dist/2ByteASR/tools/mpv/mpv.exe'
    if original_mpv.is_file():env['TWOBYTEASR_MPV']=str(original_mpv)
    profile=out/'local/2ByteASR/SubtitleStudioPreview';profile.mkdir(parents=True)
    (profile/'settings.json').write_text(json.dumps({'project_root':str(out/'library'),
        'studio_preferences':{'auto_cover':False,'recovery_policy':'official'}}),'utf8')
    sampler=subprocess.Popen([sys.executable,'-B',str(root/'scripts/long_interaction_resources.py'),'--output',str(out)],
        cwd=root,creationflags=subprocess.CREATE_NO_WINDOW)
    uia=None
    if args.uia:
        uia=subprocess.Popen(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile',
            '-ExecutionPolicy','Bypass','-File',str(root/'scripts/query_long_project_accessibility.ps1'),
            '-OutputDirectory',str(out)],cwd=root,creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=(out/'uia-stdout.log').open('wb'),stderr=(out/'uia-stderr.log').open('wb'))
    stop=threading.Event();helpers=[]
    def capture_native():
        probe=root/'tools/diagnostics/native_crash_probe.exe'
        if not probe.exists():return
        for _ in range(120):
            if stop.wait(.25):return
            try:r=json.loads((out/'result.json').read_text('utf8'));pid=int(r['pid'])
            except (OSError,ValueError,KeyError):continue
            folder=out/'native';folder.mkdir(exist_ok=True)
            helpers.append(subprocess.Popen([str(probe),str(pid),str(folder),'--first-access'],creationflags=subprocess.CREATE_NO_WINDOW))
            return
    monitor=threading.Thread(target=capture_native,daemon=True);monitor.start()
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.baseline and not args.exe:
        baseline=args.baseline.resolve()
        modules={'.'.join(p.relative_to(baseline).with_suffix('').parts):str(p)
                 for p in (baseline/'twobyteasr').rglob('*.py')
                 if 'acceptance' not in p.parts and (root/p.relative_to(baseline)).is_file()
                 and (root/p.relative_to(baseline)).read_bytes()!=p.read_bytes()}
        entry=out/'baseline_entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'
            +'sys.path.insert(0,'+repr(str(root))+')\nmodules='+repr(modules)+'\n'
            +'class Before(importlib.abc.MetaPathFinder):\n'
            +' def find_spec(self,name,path=None,target=None):\n'
            +'  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            +'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(root/'quick_start.py'))+',run_name="__main__")\n','utf8')
        (out/'baseline-module-map.json').write_text(json.dumps(modules,indent=2),'utf8')
        command=[sys.executable,'-B',str(entry)]
        env['REAL_LONG_BASELINE']='1'
    try:
        code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=760,
                            desktop_name='Default' if args.visible else None)
    finally:
        stop.set();(out/'resources-stop').touch()
        try:sampler.wait(8)
        except subprocess.TimeoutExpired:sampler.terminate();sampler.wait(5)
        if uia is not None:
            try:uia.wait(5)
            except subprocess.TimeoutExpired:uia.terminate();uia.wait(5)
    file=out/'result.json';r=json.loads(file.read_text('utf8')) if file.exists() else {}
    r.update(exit_code=code,original_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==before,
             original_sha256=before)
    file.write_text(json.dumps(r,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:r.get(k) for k in ('passed','exit_code','error','checks','original_unchanged')},ensure_ascii=False))
    return 0 if code==0 and r.get('passed') and r['original_unchanged'] else 1

if __name__=='__main__':raise SystemExit(main())
