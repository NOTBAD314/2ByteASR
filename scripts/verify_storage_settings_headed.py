from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path)
    args=parser.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():raise ValueError('Fresh tmp output required')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output);os.environ['TWOBYTEASR_STARTUP_TRACE']=str(output/'startup-trace.jsonl')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    seed=output/'seed.2byteproj';save_project(SubtitleProject(media=StudioMedia(path='')),seed)
    from twobyteasr.playback.audio_engine import studio_ffmpeg_path
    from twobyteasr.system.processes import run_hidden_subprocess
    generated=run_hidden_subprocess([str(studio_ffmpeg_path()),'-hide_banner','-loglevel','error','-nostdin',
        '-f','lavfi','-i','testsrc2=duration=2:size=160x90:rate=15','-c:v','libx264','-preset','ultrafast',
        str(output/'sole-proxy-fixture.mp4')],capture_output=True,purpose='two second isolated asset preservation fixture',timeout=30)
    if generated.returncode:raise RuntimeError(str(generated.stderr))
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_ACCEPTANCE_SCENARIO='storage-settings',
        TWOBYTEASR_STARTUP_PROJECT=str(seed),TWOBYTEASR_INVOKER_CWD=str(ROOT),QT_QPA_PLATFORM='windows',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    for key in ('QT_SCALE_FACTOR','QT_FONT_DPI','QT_ENABLE_HIGHDPI_SCALING','QT_SCALE_FACTOR_ROUNDING_POLICY'):env.pop(key,None)
    from isolated_windows_desktop import run_on_desktop
    launch=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(launch,cwd=ROOT,env=env,output=output/'process',timeout=180)
    receipt=output/'result.json';result=json.loads(receipt.read_text('utf8')) if receipt.is_file() else dict(passed=False,error='No GUI receipt')
    result['process_exit']=code;result['passed']=bool(result.get('passed') and code==0 and result.get('provider_calls')==0)
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],checks=len(result.get('checks',[])),error=result.get('error'),output=str(output)),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
