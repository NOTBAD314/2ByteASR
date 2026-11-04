"""Normal MainWindow/real-mpv source monitor acceptance in an isolated desktop."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--size', default='1600x1000')
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--layout-only', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('Use a fresh directory under repository tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project
    from twobyteasr.system.processes import run_hidden_subprocess
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    fixtures = args.fixtures.resolve() if args.fixtures else out/'fixtures'
    fixtures.mkdir(exist_ok=True)
    def encode(name, options):
        target = fixtures/name
        if not target.is_file():
            run_hidden_subprocess([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', *options, str(target)],
                purpose='source monitor acceptance fixture', check=True, timeout=180)
        return target
    base=encode('sequence.mp4',['-f','lavfi','-i','color=c=0x303030:s=320x180:r=25:d=90',
        '-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=90',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac'])
    encode('source-two-audio.mp4',['-f','lavfi','-i','color=c=red:s=320x180:r=25:d=20',
        '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=20',
        '-f','lavfi','-i','sine=frequency=1760:sample_rate=48000:duration=20',
        '-vf',"drawbox=color=green:t=fill:enable='between(t,10,14.999)',drawbox=color=blue:t=fill:enable='gte(t,15)'",
        '-map','0:v','-map','1:a','-map','2:a','-metadata:s:a:0','title=880 Hz',
        '-metadata:s:a:1','title=1760 Hz','-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac'])
    encode('music.wav',['-f','lavfi','-i','sine=frequency=660:sample_rate=48000:duration=12','-af','afade=t=in:d=1,afade=t=out:st=9:d=3','-c:a','pcm_s16le'])
    encode('silent.mp4',['-f','lavfi','-i','testsrc2=s=320x180:r=25:d=12','-an','-c:v','libx264','-preset','ultrafast','-threads','2'])
    encode('long-source.mp4',['-f','lavfi','-i','color=c=0x405060:s=160x90:r=1:d=7200',
        '-f','lavfi','-i','sine=frequency=330:sample_rate=8000:duration=7200',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac','-b:a','16k'])
    project=SubtitleProject(media=StudioMedia(str(base),duration_ms=90000,width=320,height=180),
        cues=[StudioCue('preserve-caption',1000,4000,'现有字幕保持时序')],
        studio_state={'playhead_ms':60000})
    save_project(project,out/'project.2byteproj')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_STARTUP_SIZE=args.size,
        TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='source-monitor',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        SOURCE_MONITOR_FIXTURES=str(fixtures),SOURCE_MONITOR_LAYOUT_ONLY=str(int(args.layout_only)),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.scale),PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop([sys.executable,'-B',str(ROOT/'quick_start.py')],cwd=ROOT,env=env,
        output=out/'process',timeout=600)
    result_path=out/'result.json'
    result=json.loads(result_path.read_text('utf8')) if result_path.is_file() else {'error':'No acceptance result'}
    result['exit_code']=code; result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if code==0 and result.get('finished') and not result.get('error') and all(result.get('checks',{}).values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
