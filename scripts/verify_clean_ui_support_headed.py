"""One normal, isolated application: Home export, Studio controls and tutorial."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--theme',default='sand',choices=('sand','grape'))
    parser.add_argument('--scale',default='1')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('fresh source/tmp output required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import save_project
    from verify_speaker_board_headed import project
    fixture=project()
    from twobyteasr.recognition import speech_coverage
    fixture.generation_metadata[speech_coverage.KEY]=speech_coverage.make_state([
        dict(start=2,end=3,detector='firered_vad',confidence=.99),
        dict(start=4,end=5,detector='energy',confidence=.2)],[],duration=20,identity='acceptance-audio')
    media=out/'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y',
        '-f','lavfi','-i','color=c=0x252131:size=960x540:rate=24:duration=8',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=8',
        '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(media)],
        check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    fixture.media.path=str(media)
    save_project(fixture,out/'fixture.2byteproj')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,QT_FONT_DPI='96',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='clean-ui-original-mg-support',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_ACCEPTANCE_THEME=args.theme,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO',None)
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=240,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    print(json.dumps(dict(exit=code,passed=result.get('passed'),checks=len(result.get('checks',[])),error=result.get('error'),output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
