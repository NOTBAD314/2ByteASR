"""Source/frozen entry on a private desktop; never changes system audio state."""
import argparse, json, os, shutil, sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--phase', default='initial')
    args=parser.parse_args(); out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'): raise ValueError('tmp required')
    out.mkdir(parents=True,exist_ok=True)
    baseline=root/'tmp/config-audio-fidelity/baseline'
    if args.phase=='initial':
        (out/'config').mkdir(exist_ok=True)
        shutil.copy2(baseline/'settings.json',out/'config/2byteasr_settings.json')
        (out/'local/2ByteASR').mkdir(parents=True,exist_ok=True)
        shutil.copy2(baseline/'profiles.json',out/'local/2ByteASR/profiles.json')
        d=json.loads((baseline/'original.2byteproj').read_text('utf8'))
        old=d['media']['path']; new=str(baseline/'original.mp3')
        (out/'original.2byteproj').write_text(json.dumps(d,ensure_ascii=False).replace(old.replace('\\','\\\\'),new.replace('\\','\\\\')),'utf8')
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,save_project
    video=root/'tmp/studio-multisource-20260928/assets/first.mp4'
    if not video.exists(): raise FileNotFoundError(video)
    p=SubtitleProject(media=StudioMedia(path=str(video),duration_ms=10000,width=1280,height=720));p.validate()
    save_project(p,out/'video.2byteproj')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='config-audio-fidelity',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'original.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_FIDELITY_PHASE=args.phase,TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONIOENCODING='utf8')
    helper=root/'tmp/config-audio-fidelity/capture-loopback.exe'
    if helper.is_file():env['TWOBYTEASR_PROCESS_LOOPBACK']=str(helper)
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command+[str(out/'original.2byteproj')],cwd=root,env=env,output=out/('process-'+args.phase),timeout=360)
    result=json.loads((out/(args.phase+'-result.json')).read_text('utf8'))
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'error':result.get('error'),'exit':code},ensure_ascii=False))
    return 0 if result['passed'] and code==0 else 1


if __name__=='__main__':raise SystemExit(main())
