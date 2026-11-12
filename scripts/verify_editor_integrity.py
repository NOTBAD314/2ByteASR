"""Normal-entry, native Windows paint measurements; fixtures are synthetic."""
import argparse, ctypes, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scale',type=float,default=1)
    parser.add_argument('--count',type=int,default=2000)
    parser.add_argument('--cycles',type=int,default=100)
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--performance',action='store_true')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--real-project',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh output under source/tmp required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    media=out/'synthetic.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i',
        'testsrc2=size=960x540:rate=30:duration=16','-f','lavfi','-i','sine=frequency=440:duration=16',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac','-shortest',str(media)],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    from twobyteasr.subtitle_rules import subtitle_translation as st
    step=350 if args.count<=2000 else 1800
    cues=[StudioCue(f'cue-{i}',i*step,i*step+step-20,'他这里会打打雪仗我们走吧，她也在营第。') for i in range(args.count)]
    project=SubtitleProject(StudioMedia(str(media),duration_ms=max(744000,args.count*step),width=960,height=540),cues=cues)
    project.generation_metadata.update(translations={c.id:'He is here, and she is there.' for c in cues},
        translation_records=dict(version=1,target='en',records={c.id:st._record('He is here, and she is there.',c.text,origin=st.ORIGIN_MANUAL) for c in cues},history=[]))
    save_project(project,out/'project.2byteproj');save_project(SubtitleProject(StudioMedia('')),out/'entry.2byteproj')
    real_info=None
    if args.real_project:
        import hashlib,shutil
        original=args.real_project.resolve();copied=out/'real-project.2byteproj'
        shutil.copy2(original,copied)
        real_info=dict(path=str(original),sha256=hashlib.sha256(original.read_bytes()).hexdigest(),copy=str(copied))
        (out/'real-input.json').write_text(json.dumps(real_info,indent=2),'utf8')
    user=ctypes.windll.user32;user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    previous=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4));native=user.GetDpiForSystem()/96
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.scale/native),PYTHONUTF8='1',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-integrity',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'entry.2byteproj'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),EDITOR_INTEGRITY_PROJECT=str(out/'project.2byteproj'),
        EDITOR_INTEGRITY_CYCLES=str(args.cycles),EDITOR_INTEGRITY_BASELINE='1' if args.baseline else '0',
        EDITOR_INTEGRITY_PERFORMANCE='1' if args.performance else '0')
    if real_info:env['EDITOR_INTEGRITY_REAL']=real_info['copy']
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=600,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    if real_info:
        result['real_original_unchanged']=hashlib.sha256(Path(real_info['path']).read_bytes()).hexdigest()==real_info['sha256']
        result['passed']=bool(result.get('passed') and result['real_original_unchanged'])
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result.get('passed',False),exit=code,output=str(out),error=result.get('error')),ensure_ascii=False))
    return 0 if result.get('passed') and code==0 else 1
if __name__=='__main__':raise SystemExit(main())
