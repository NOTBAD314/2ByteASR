"""Run Devin integration through normal source, frozen GUI, or original launcher."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--exe',type=Path)
    args=p.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh source/tmp output required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,save_project
    from twobyteasr.system.processes import run_hidden_subprocess
    media=out/'fixture.mp4'
    run_hidden_subprocess([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-hide_banner','-loglevel','error','-y',
        '-f','lavfi','-i','color=c=0x293540:s=640x360:r=12:d=12','-c:v','libx264','-preset','ultrafast',str(media)],check=True,purpose='integration fixture')
    project=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=12000),cues=[
        StudioCue('c'+str(i),i*1500,i*1500+1300,'This is test line '+str(i)) for i in range(6)])
    project.generation_metadata['language']={'code':'en'}
    save_project(project,out/'input.2byteproj')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='devin-daily',TWOBYTEASR_STARTUP_PROJECT=str(out/'input.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='0',TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    from audit_launch_bridge import run_audit_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(cmd,cwd=ROOT,env=env,output=out,timeout=240,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf-8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(passed=result.get('passed'),exit_code=code,checks=len(result.get('checks',[])),errors=result.get('errors')),ensure_ascii=False))
    return code or (0 if result.get('passed') else 1)

if __name__=='__main__':raise SystemExit(main())
