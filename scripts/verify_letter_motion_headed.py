"""Own isolated data and desktop for the curated-letter acceptance fixture."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--theme',default='grape')
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Output must be under repository tmp/')
    output.mkdir(parents=True,exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output/'data'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    sys.path.insert(0,str(ROOT))
    if args.child or args.render:
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.acceptance.letter_motion_audit import run_window,render_outputs
        return render_outputs(output) if args.render else run_window(output,args.theme)
    media=output/'source.mp4'
    if not media.exists():
        subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'),'-hide_banner','-loglevel','error',
            '-f','lavfi','-i','color=c=0x203344:s=960x540:r=30:d=36',
            '-c:v','libx264','-pix_fmt','yuv420p',str(media)],check=True)
    from isolated_windows_desktop import run_on_desktop
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1')
    code=run_on_desktop([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--output',str(output),
        '--child','--theme',args.theme],cwd=ROOT,env=env,output=output/'process',timeout=180)
    print((output/'result.json').read_text('utf-8') if (output/'result.json').exists() else 'No result')
    return code


if __name__=='__main__':
    raise SystemExit(main())
