"""Normal-window regression for stable captions, save/undo and real burn-in."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--normal-entry', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):
        parser.error('output must be under source/tmp')
    output.mkdir(parents=True, exist_ok=args.child)
    if args.exe or args.normal_entry:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
        startup=save_project(SubtitleProject(StudioMedia('')), output/'startup.2byteproj')
        env=dict(os.environ, QT_QPA_PLATFORM='windows', TWOBYTEASR_ACCEPTANCE_DIR=str(output),
            TWOBYTEASR_ACCEPTANCE_SCENARIO='stable-captions', TWOBYTEASR_STARTUP_PROJECT=str(startup),
            TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
            HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        from audit_launch_bridge import run_audit_on_desktop
        command=[str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
        code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=output,
            timeout=300,receipt=output/'result.json')
        (output/'exit.json').write_text(json.dumps({'exit_code':code}),'utf8')
        return code
    if not args.child:
        from isolated_windows_desktop import run_on_desktop
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM='windows', TWOBYTEASR_TEST_ROOT=str(output/'profile'),
            TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        code = run_on_desktop([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
            '--child', '--output', str(output)], cwd=ROOT, env=env,
            output=output/'process', timeout=240)
        (output/'exit.json').write_text(json.dumps({'exit_code': code}), 'utf8')
        return code
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.stable_captions_audit import run
    return run(output)


if __name__ == '__main__':
    raise SystemExit(main())
