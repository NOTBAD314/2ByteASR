"""Verify a normal application, actual clock and persisted switch in 3 starts."""
import argparse,ctypes,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path);p.add_argument('--scale',type=float,default=1)
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('fresh source/tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    media=out/'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i',
        'testsrc2=size=960x540:rate=30:duration=12','-c:v','libx264','-preset','ultrafast','-threads','2',str(media)],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    save_project(SubtitleProject(StudioMedia(str(media),duration_ms=12000,width=960,height=540),
        cues=[StudioCue('a',0,5000,'第一条字幕'),StudioCue('b',5100,10000,'第二条字幕')]),out/'fixture.2byteproj')
    user=ctypes.windll.user32;user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    previous=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4));native=user.GetDpiForSystem()/96
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(a.scale/native),PYTHONUTF8='1',PYTHONPATH='',
        TWOBYTEASR_EDITOR_BACKGROUND_AUDIT='1',TWOBYTEASR_PLAYHEAD_CENTER_AUDIT='1',
        TWOBYTEASR_ACCEPTANCE_PROFILE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-download',TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(a.exe.resolve())] if a.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    rows=[]
    for phase in ('initial','restart-off','restart-on'):
        phaseout=out/phase;phaseout.mkdir()
        shutil.copyfile(out/'fixture.2byteproj',phaseout/'fixture.2byteproj')
        active=dict(env,TWOBYTEASR_ACCEPTANCE_DIR=str(phaseout),TWOBYTEASR_CENTER_PHASE=phase,
                    TWOBYTEASR_STARTUP_PROJECT=str(phaseout/'fixture.2byteproj'))
        code=run_audit_on_desktop(command,cwd=ROOT,env=active,output=phaseout,timeout=180,receipt=phaseout/'result.json')
        result=json.loads((phaseout/'result.json').read_text('utf8')) if (phaseout/'result.json').is_file() else {}
        row=dict(phase=phase,exit=code,passed=result.get('passed'),checks=len(result.get('checks',{})),error=result.get('error'))
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        if code or not result.get('passed'):break
    passed=len(rows)==3 and all(r['exit']==0 and r['passed'] for r in rows)
    (out/'summary.json').write_text(json.dumps(dict(passed=passed,runs=rows),ensure_ascii=False,indent=2),'utf8')
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
