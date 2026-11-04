"""Normal quick_start/EXE, private Windows desktop, six-second local fixture."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--scale',default='natural')
    args=parser.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh task directory under repository tmp')
    output.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output),TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.playback.audio_engine import studio_ffmpeg_path
    command=[str(studio_ffmpeg_path()),'-hide_banner','-loglevel','error','-nostdin','-y',
        '-f','lavfi','-i','testsrc2=duration=6:size=320x180:rate=30',
        '-f','lavfi','-i','sine=frequency=600:duration=6:sample_rate=48000',
        '-c:v','libx264','-preset','ultrafast','-g','30','-c:a','aac','-b:a','64k',
        '-f','flv',str(output/'short-source.flv')]
    generated=run_hidden_subprocess(command,capture_output=True,purpose='six-second isolated storage acceptance media',timeout=30)
    if generated.returncode:raise RuntimeError(str(generated.stderr))
    (output/'fixture-command.json').write_text(json.dumps(command,ensure_ascii=False,indent=2),'utf8')
    (output/'short-source.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\n短素材原路径预览\n\n2\n00:00:02,000 --> 00:00:04,000\n重复寻址与缓存槽\n\n3\n00:00:04,000 --> 00:00:06,000\n关闭工程回收临时像素\n','utf8')
    from twobyteasr.projects.studio_project import StudioMedia,SubtitleProject,save_project
    fixture=output/'projects'/'seed'/'seed.2byteproj';fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='',duration_ms=0)),fixture)
    env=os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE','TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key,None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='storage-media',
        TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_INVOKER_CWD=str(ROOT),QT_QPA_PLATFORM='windows',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    if args.scale=='natural':
        for key in ('QT_SCALE_FACTOR','QT_ENABLE_HIGHDPI_SCALING','QT_FONT_DPI','QT_SCALE_FACTOR_ROUNDING_POLICY'):env.pop(key,None)
    else:env.update(QT_SCALE_FACTOR=args.scale,QT_ENABLE_HIGHDPI_SCALING='0',QT_FONT_DPI='96')
    from isolated_windows_desktop import run_on_desktop
    launch=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(launch,cwd=ROOT,env=env,output=output/'process',timeout=180)
    receipt=output/'result.json'
    result=json.loads(receipt.read_text('utf8')) if receipt.is_file() else dict(passed=False,error='No normal GUI receipt')
    result['process_exit']=code
    result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result.get('provider_calls')==0)
    time.sleep(.3)
    folder=Path(result.get('overlay_folder',output/'missing-overlay'))
    remaining=[path for directory in (folder,folder/'caption-prepared',folder/'caption-scenes')
        for path in directory.glob('*.rgba')]
    result['after_process']=dict(raw_files=len(remaining),raw_bytes=sum(p.stat().st_size for p in remaining if p.is_file()),
        raw_paths=[str(p) for p in remaining],session_exists=folder.exists())
    result['passed']=bool(result['passed'] and not remaining and not folder.exists())
    result['fixture_bytes']=(output/'short-source.flv').stat().st_size
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],checks=len(result.get('checks',[])),error=result.get('error'),
        after_process=result['after_process'],output=str(output)),ensure_ascii=False),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
