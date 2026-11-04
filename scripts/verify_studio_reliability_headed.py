"""Normal source/EXE reliability workflow with isolated copied inputs."""
import argparse,hashlib,json,os,shutil,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
    parser.add_argument('--launcher',type=Path);parser.add_argument('--entry-bridge',type=Path)
    parser.add_argument('--visible',action='store_true');parser.add_argument('--mpv',type=Path,required=True)
    parser.add_argument('--caption-integrity',action='store_true')
    parser.add_argument('--full-static',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):parser.error('Use a new source/tmp output directory')
    out.mkdir(parents=True);shutil.copy2(args.project,out/'project.2byteproj')
    checksum=hashlib.sha256(args.project.read_bytes()).hexdigest()
    (out/'input.json').write_text(json.dumps(dict(source_sha256=checksum,visible=args.visible)),'utf8')
    original_local=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out);sys.path.insert(0,str(root))
    from twobyteasr.test_isolation import install
    install()
    fonts=Path(os.environ['LOCALAPPDATA'])/'Microsoft/Windows/Fonts';fonts.mkdir(parents=True,exist_ok=True)
    for name in ('猫啃什锦黑.ttf','优设标题黑.ttf','SourceHanSansSC-VF.otf'):
        source=original_local/'Microsoft/Windows/Fonts'/name
        if source.is_file():shutil.copy2(source,fonts/name)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-reliability',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_STARTUP_SIZE='1400x780',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TWOBYTEASR_MPV=str(args.mpv.resolve()))
    if args.caption_integrity:env['TWOBYTEASR_CAPTION_INTEGRITY_AUDIT']='1'
    if args.full_static:
        env['TWOBYTEASR_FULL_STATIC_AUDIT']='1'
        env['TWOBYTEASR_CAPTION_INTEGRITY_AUDIT']='1'
    timeout=2200 if args.full_static else 500
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.launcher:
        if not args.exe or not args.entry_bridge:parser.error('--launcher needs --exe and --entry-bridge')
        command=[sys.executable,'-B',str(args.entry_bridge.resolve()),'--launcher',str(args.launcher.resolve()),
                 '--gui',str(args.exe.resolve()),'--output',str(out),'--timeout','480']
    if args.visible:
        import subprocess
        with (out/'process.stdout.txt').open('wb') as stdout,(out/'process.stderr.txt').open('wb') as stderr:
            process=subprocess.Popen(command,cwd=root,env=env,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:process.terminate();process.wait(10);code=-1
    else:
        from isolated_windows_desktop import run_on_desktop
        code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=timeout)
    path=out/'result.json';data=json.loads(path.read_text('utf8')) if path.exists() else {}
    data.update(process_exit=code,input_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==checksum)
    data['passed']=bool(data.get('passed') and data.get('gui_shutdown') and code==0 and data['input_unchanged'])
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:data.get(k) for k in ('passed','error','process_exit','input_unchanged')},ensure_ascii=False))
    return 0 if data['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
