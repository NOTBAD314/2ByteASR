"""Measure real Studio controls on an isolated Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--counts',default='60,600,3000')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--exports',action='store_true')
    parser.add_argument('--pixels',action='store_true')
    parser.add_argument('--geometry',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('fresh repository tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    ffmpeg=root/'tools/ffmpeg/ffmpeg.exe'
    if not ffmpeg.exists():ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
    media=root/'tmp/workbench-perf/基準 素材.mp4'
    if not media.exists():
        media.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-f','lavfi','-i',
            'color=c=0x24404b:s=1280x720:r=30','-f','lavfi','-i','sine=frequency=440:sample_rate=44100',
            '-t','12','-c:v','libx264','-preset','fast','-crf','20','-c:a','aac',str(media)],
            check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    entry=save_project(SubtitleProject(media=StudioMedia('',duration_ms=0)),out/'entry.2byteproj')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='workbench-performance',TWOBYTEASR_STARTUP_PROJECT=str(entry),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_PERF_GEOMETRY='1' if args.geometry else '0',TWOBYTEASR_PERF_PIXELS='1' if args.pixels else '0',TWOBYTEASR_PERF_EXPORTS='1' if args.exports else '0',TWOBYTEASR_PERF_MEDIA=str(media),TWOBYTEASR_PERF_COUNTS=args.counts,QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=500)
    path=out/'result.json'
    result=json.loads(path.read_text('utf8')) if path.exists() else {}
    print(json.dumps(dict(exit_code=code,completed=result.get('completed'),passed=result.get('passed',True),checks=len(result.get('checks',[])),support=result.get('support'),
        error=(out/'error.txt').read_text('utf8') if (out/'error.txt').exists() else None,output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('completed') and result.get('passed',True) else 1


if __name__=='__main__':raise SystemExit(main())
