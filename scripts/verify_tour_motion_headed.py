"""Real-window frame log of the first-run tutorial (2026-10-14, tutorial motion round).

A first launch in a fresh isolated profile on a private Windows desktop: the
quick chooser is answered "稍后再说", the tutorial starts, and
twobyteasr/acceptance/tour_motion_audit.py walks it the way a person does (real clicks on
the outlined controls) while it logs every paint of the overlay and films the
changes of step. Theme and interface zoom default to the user's (slate, 110%).

No real user data is read or written, no network is used. Use --exe for a
frozen candidate.

usage: python scripts/verify_tour_motion_headed.py --output tmp/tour-motion/run1 [--theme slate] [--zoom 110]
       [--exe dist/2ByteASR/2ByteASR.exe] [--click real|helper] [--language ja] [--choose cloud] [--tooltips]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAKE_INPUT = r'''
import json, sys
from pathlib import Path
from twobyteasr.app import sample_project
from twobyteasr.projects.studio_project import load_project, save_project
target = Path(sys.argv[1])
sample_project.sample_root = lambda: target / "media"
path = sample_project.ensure_sample_project()
project = load_project(path)
project.generation_metadata.pop("sample_project", None)
saved = save_project(project, target / "project" / "demo")
print(json.dumps(dict(project=str(saved))))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--theme', default='slate')
    parser.add_argument('--zoom', type=int, default=110)
    parser.add_argument('--click', default='real', choices=('real', 'helper'))
    parser.add_argument('--language', default='', choices=('', 'zh', 'zh-Hant', 'ja', 'en', 'ko'),
                        help='language picked in the plan window\'s language row (2026-10-24: the first step)')
    parser.add_argument('--choose', default='', choices=('', 'cloud'),
                        help='answer the first-run chooser with this card instead of 稍后再说 (2026-10-21)')
    parser.add_argument('--tooltips', action='store_true',
                        help='also show and picture one chooser and one tutorial tooltip at --zoom (2026-10-21)')
    parser.add_argument('--models', type=Path, help='a models folder linked read-only into the isolated model root '
                        '(the home cards then show installed models, e.g. the Japanese CTC aligner)')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    profile = out / 'profile'
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               PYTHONFAULTHANDLER='1', NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9',
               HTTPS_PROXY='http://127.0.0.1:9')
    done = subprocess.run([sys.executable, '-X', 'utf8', '-c', MAKE_INPUT, str(out / 'input')], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, encoding='utf-8')
    if done.returncode:
        raise SystemExit(done.stderr[-3000:])
    spec = json.loads(done.stdout.strip().splitlines()[-1])
    (out / 'input.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf-8')
    # The isolated QSettings the app will read (same test root): the user's theme and zoom.
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(profile)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.app import ui_zoom
    from twobyteasr.design.theme_manager import save_theme_key
    ui_zoom.set_zoom_percent(args.zoom)
    save_theme_key(args.theme)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from verify_ui_polish_headed import _link_models, _unlink
    links = _link_models(args.models.resolve(), Path(os.environ['2BYTEASR_MODEL_ROOT'])) if args.models else []
    if links:
        env['2BYTEASR_MODEL_ROOT'] = os.environ['2BYTEASR_MODEL_ROOT']
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='tour-motion',
               TWOBYTEASR_STARTUP_PROJECT=spec['project'], TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_TOUR_CLICK=args.click, TWOBYTEASR_TOUR_LANGUAGE=args.language,
               TWOBYTEASR_TOUR_CHOOSE=args.choose, TWOBYTEASR_TOUR_TOOLTIPS='1' if args.tooltips else '0',
               QT_QPA_PLATFORM='windows')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    try:
        code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    finally:
        _unlink(links)
    path = out / 'result-tour.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=result.get('passed'), exit=code, shutdown=result.get('gui_shutdown'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   error=(result.get('error') or '')[-1500:])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] and code == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
