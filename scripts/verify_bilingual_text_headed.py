"""Normal source entry with owned projects/media on a private Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--launcher',type=Path)
    parser.add_argument('--entry-bridge',type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a new directory under repository tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core as legacy
    legacy.add_learned_mapping('双语验收词库','那维莱特','那维莱特',category='角色',origin='手动')
    legacy.add_learned_mapping('双语验收词库','那维来特','那维莱特',category='角色',origin='手动')
    identity = legacy.resolve_glossary_identity('双语验收词库')
    media = output/'synthetic.mp4'
    subprocess.run([str(args.ffmpeg),'-hide_banner','-loglevel','error','-f','lavfi','-i',
                    'color=c=0x18202b:s=1280x720:r=24:d=12','-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
                    '-t','12','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-y',str(media)],check=True)
    from twobyteasr.acceptance.bilingual_text_audit import fixture
    from twobyteasr.projects.studio_project import save_project
    project_path = output/'owned.2byteproj'
    save_project(fixture(media=str(media),glossary_id=identity),project_path)
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='bilingual-text',
        TWOBYTEASR_STARTUP_PROJECT=str(project_path), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_MAIN_PYTHON=sys.executable, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.launcher:
        if not args.exe or not args.entry_bridge:parser.error('--launcher needs --exe and --entry-bridge')
        command=[sys.executable,'-B',str(args.entry_bridge.resolve()),'--launcher',str(args.launcher.resolve()),
                 '--gui',str(args.exe.resolve()),'--output',str(output),'--timeout','240']
    code = run_on_desktop(command,cwd=ROOT,env=env,output=output/'process',timeout=260)
    path = output/'result.json'
    result = json.loads(path.read_text('utf-8')) if path.is_file() else {'passed':False,'error':'missing receipt'}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code==0)
    if args.exe:
        expected=json.loads((args.exe.parent/'2byteasr_build.json').read_text('utf-8'))
        result['in_process_build_matched']=(result.get('identity') or {}).get('git_sha')==expected['git_sha'] and result.get('frozen')
        result['passed']=bool(result['passed'] and result['in_process_build_matched'])
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'passed':result['passed'],'checks':len(result.get('checks',[])),'output':str(output),'process_exit':code},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
