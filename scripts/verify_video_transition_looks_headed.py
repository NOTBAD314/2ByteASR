"""Real-window check for video seam transition looks, on a private desktop.

  .venv-main/Scripts/python.exe -X utf8 scripts/verify_video_transition_looks_headed.py --output tmp/<new dir> [--theme warm] [--no-export]
      standalone Studio page from source
  ... --exe <path>\\2ByteASR.exe    the same audit inside a packaged app (scenario video-transition-looks)
  ... --normal-entry               the same scenario through quick_start.py (source)

Isolated data under the output folder; generated media only; no user files.
"""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--no-export', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--normal-entry', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Output must be under repository tmp/')
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output/'data'), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
                      TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    sys.path.insert(0, str(ROOT))
    if args.child:
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.acceptance.video_transition_looks_audit import run_window
        return run_window(output, args.theme, export=not args.no_export)
    sys.path.insert(0, str(ROOT/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    if args.exe or args.normal_entry:
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
        # The scenario needs its own project file under the output; the audit opens its fixture itself.
        startup = save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), output/'startup.2byteproj')
        env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_STARTUP_')}
        env.update(QT_QPA_PLATFORM='windows', PYTHONUTF8='1', TWOBYTEASR_ACCEPTANCE_DIR=str(output),
                   TWOBYTEASR_ACCEPTANCE_SCENARIO='video-transition-looks', TWOBYTEASR_INVOKER_CWD=str(ROOT),
                   TWOBYTEASR_STARTUP_PROJECT=str(startup), TWOBYTEASR_TRANSITION_AUDIT_THEME=args.theme,
                   TWOBYTEASR_TRANSITION_AUDIT_EXPORT='0' if args.no_export else '1')
        command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output/f'process-{args.theme}', timeout=600)
        path = output/f'result-{args.theme}.json'
        result = json.loads(path.read_text('utf-8')) if path.exists() else {}
        passed = code == 0 and result.get('passed') and result.get('gui_shutdown')
        print(json.dumps(dict(passed=bool(passed), checks=len(result.get('checks', [])), exit=code,
                              frozen=result.get('frozen'), executable=result.get('executable'),
                              failed=[c['name'] for c in result.get('checks', []) if not c['passed']],
                              error=result.get('error')), ensure_ascii=False))
        return 0 if passed else 1
    env = dict(os.environ, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', PYTHONUTF8='1')
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--output', str(output), '--child',
               '--theme', args.theme]
    if args.no_export:
        command.append('--no-export')
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/f'process-{args.theme}', timeout=600)
    result = output/f'result-{args.theme}.json'
    print(result.read_text('utf-8') if result.exists() else 'No result')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
