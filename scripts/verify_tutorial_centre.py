"""Tutorial centre acceptance through normal MainWindow and the actual entry."""
import argparse, ctypes, json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path);p.add_argument('--scale',type=float,default=1)
    p.add_argument('--baseline',action='store_true');a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('fresh source/tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    media=out/'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i',
        'testsrc2=size=960x540:rate=12:duration=12','-c:v','libx264','-preset','ultrafast','-threads','2',str(media)],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    project=SubtitleProject(StudioMedia(str(media),duration_ms=12000,width=960,height=540),cues=[
        StudioCue('a',0,5000,'她如果真的不是的话，他和它在营第等我。'),
        StudioCue('b',5100,10000,'她在第一行\n他和它在营第。')])
    from twobyteasr.subtitle_rules import subtitle_translation as st
    text='她和他一起到营第。'
    project.generation_metadata.update(translations={'a':text},translation_records=dict(version=1,target='zh',
        records={'a':st._record(text,project.cues[0].text,origin=st.ORIGIN_MANUAL)},history=[]))
    save_project(project,out/'fixture.2byteproj')
    user=ctypes.windll.user32;user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    previous=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4));native=user.GetDpiForSystem()/96
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(a.scale/native),PYTHONUTF8='1',
        TWOBYTEASR_EDITOR_BACKGROUND_AUDIT='1',TWOBYTEASR_TUTORIAL_CENTRE_AUDIT='1',TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-download',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),EDITOR_DOWNLOAD_BASELINE='1' if a.baseline else '0',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(a.exe.resolve())] if a.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=1200,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(output=str(out),exit=code,passed=result.get('passed'),checks=len(result.get('checks',{})),error=result.get('error')),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1

if __name__=='__main__':raise SystemExit(main())
