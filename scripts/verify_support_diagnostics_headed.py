"""Normal-window diagnostic workflow, isolated media/settings and Windows desktop."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
    parser.add_argument('--source-root',type=Path);parser.add_argument('--bench',action='store_true')
    parser.add_argument('--theme',default='grape',choices=('grape','warm'))
    parser.add_argument('--tooltips-zoom',type=int,choices=(100,110,120,135,150,175,200),
                        help='tooltip-only pass at this interface zoom (preset in the isolated settings)')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():parser.error('fresh repository tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    if args.tooltips_zoom:
        from PySide6.QtCore import QSettings
        settings=QSettings('2ByteASR','2ByteASR')  # the isolated class after install()
        settings.setValue('ui/zoom_percent',args.tooltips_zoom);settings.sync()
    from twobyteasr.projects.studio_project import StudioMedia,StudioCue,SubtitleProject,save_project
    media=out/'generated.mp4'
    if not args.bench:
        ffmpeg=root/'tools/ffmpeg/ffmpeg.exe'
        if not ffmpeg.is_file():ffmpeg=root/'tools/ffmpeg/bin/ffmpeg.exe'
        subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','12','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(media)],
                       check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    count=1000 if args.bench else 24
    p=SubtitleProject(media=StudioMedia(path='' if args.bench else str(media),duration_ms=count*500,width=640,height=360),
                      cues=[StudioCue(str(i+1),i*500,i*500+450,'日本語の診断テスト'+str(i),speaker_id='S01') for i in range(count)])
    p.generation_metadata['language']={'code':'ja'};p.render_settings['_cue_domain']='timeline'
    fixture=save_project(p,out/'fixture.2byteproj')
    entry=save_project(SubtitleProject(media=StudioMedia(path='',duration_ms=0)),out/'entry.2byteproj')
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='support-diagnostics',TWOBYTEASR_STARTUP_PROJECT=str(entry),
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_SUPPORT_BENCH='1' if args.bench else '0',TWOBYTEASR_SUPPORT_THEME=args.theme,QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    if args.bench:env['TWOBYTEASR_DIAGNOSTIC_NO_PLAYER']='1'
    if args.tooltips_zoom:env['TWOBYTEASR_SUPPORT_TOOLTIPS']='1'
    cwd=(args.source_root or root).resolve();env['TWOBYTEASR_INVOKER_CWD']=str(root)
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(cwd/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=150)
    path=out/'result.json';data=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    deadline=time.monotonic()+35
    while not data.get('gui_shutdown') and time.monotonic()<deadline:
        time.sleep(.2);data=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    print(json.dumps(dict(output=str(out),exit_code=code,passed=data.get('passed'),checks=len(data.get('checks',[])),error=data.get('error')),ensure_ascii=True))
    return 0 if code==0 and data.get('passed') and data.get('gui_shutdown') else 1


if __name__=='__main__':raise SystemExit(main())
