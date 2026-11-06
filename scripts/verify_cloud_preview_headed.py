"""Normal app entry, isolated data/Windows desktop, delayed first player and analysis."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--duration',type=int,default=8)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--scale',default='0.5714285714')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('fresh checkout/tmp directory required')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i',
        f'color=c=0x213c58:s=640x360:r=2:d={args.duration}','-f','lavfi','-i',
        f'sine=frequency=440:duration={args.duration}','-c:v','libx264','-threads','2','-preset','ultrafast',
        '-pix_fmt','yuv420p','-c:a','aac','-b:a','24k','-shortest',str(out/'media.mp4')],check=True)
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    fixture = out/'blank.2byteproj'
    save_project(SubtitleProject(StudioMedia('')), fixture)
    env=dict(os.environ,TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='cloud-preview-integrity',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_MAIN_PYTHON=sys.executable,
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    for name in list(env):
        if name.endswith(('_API_KEY','_ACCESS_TOKEN','_REFRESH_TOKEN')):env.pop(name)
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop([str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')],cwd=ROOT,env=env,output=out/'process',timeout=180)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {'passed':False}
    result['exit_code']=code
    result['passed']=bool(result.get('passed') and code==0)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result['passed'],checks=len(result.get('checks',[])),output=str(out),exit=code)))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
