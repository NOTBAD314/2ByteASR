"""Real-window onboarding / punctuation / Qwen guide / shortcut acceptance (2026-10-13).

Everything lives in a fresh directory under the repository tmp/: a generated
demo project (short local video, punctuation test lines), and two isolated
data folders. Three launches on a private Windows desktop, each running
twobyteasr/onboarding_settings_audit.py inside the app:

  fresh     profile-a, a first launch
  restart   profile-a again (what the first launch saved must still be there)
  upgraded  profile-b with older settings and a recent project, started with
            the project path on the command line (what a double-click does)

No real user data is read or written, no network is used (offline guards and
refused DNS inside the app). Use --exe for a frozen candidate.

usage: python scripts/verify_onboarding_headed.py --output tmp/m7/onboarding-run1 [--exe dist/2ByteASR/2ByteASR.exe]
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
from twobyteasr import sample_project
from twobyteasr.onboarding_settings_audit import PUNCTUATION_LINES
from twobyteasr.studio_project import load_project, save_project
target = Path(sys.argv[1])
sample_project.sample_root = lambda: target / "media"
path = sample_project.ensure_sample_project()
project = load_project(path)
for cue, text in zip(project.cues, PUNCTUATION_LINES):
    cue.text = text
project.generation_metadata.pop("sample_project", None)
project.generation_metadata["canonical_terms"] = ["S0pp", "Zhe", "CHIOCHOO"]
project.validate()
saved = save_project(project, target / "project" / "demo")
media = next((target / "media").glob("*.mp4"))
print(json.dumps(dict(project=str(saved), project_id=project.project_id, media=str(media))))
'''

STUDIO_PATH = r'''
from twobyteasr.studio_project import studio_settings_path
print(studio_settings_path())
'''


def isolated(profile: Path, extra=None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               PYTHONFAULTHANDLER='1')
    env.update(extra or {})
    return env


def python_in(profile: Path, code: str, *args) -> str:
    done = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, *args], cwd=str(ROOT), env=isolated(profile),
                          capture_output=True, text=True, encoding='utf-8')
    if done.returncode:
        raise SystemExit(done.stderr[-3000:])
    return done.stdout.strip().splitlines()[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--phases', default='fresh,restart,upgraded')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    spec = json.loads(python_in(out / 'profile-gen', MAKE_INPUT, str(out / 'input')))
    spec['repo'] = str(ROOT)
    (out / 'input.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf-8')
    # An upgraded user's data folder: older keys, a recent project, no onboarding stamp.
    profile_b = out / 'profile-b'
    settings = Path(python_in(profile_b, STUDIO_PATH))
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({'recent_projects': [spec['project']],
                                    'shortcuts': {'merge_tool': 'M', 'play_pause': 'K'}}, ensure_ascii=False), 'utf-8')
    project_bytes = Path(spec['project']).read_bytes()
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    summary = {}
    for phase in [p for p in args.phases.split(',') if p]:
        profile = out / ('profile-b' if phase == 'upgraded' else 'profile-a')
        env = isolated(profile, dict(
            TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='onboarding-settings',
            TWOBYTEASR_ONBOARDING_PHASE=phase, TWOBYTEASR_STARTUP_PROJECT=spec['project'],
            TWOBYTEASR_STARTUP_TRACE=str(out / f'{phase}-startup.jsonl'), TWOBYTEASR_INVOKER_CWD=str(ROOT),
            TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
            QT_QPA_PLATFORM='windows'))
        command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
        if phase == 'upgraded':
            command.append(spec['project'])       # what Explorer passes for a double-clicked project
        code = run_on_desktop(command, cwd=ROOT, env=env, output=out / f'process-{phase}', timeout=args.timeout)
        path = out / f'result-{phase}.json'
        result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
        summary[phase] = dict(passed=result.get('passed'), exit=code, shutdown=result.get('gui_shutdown'),
                              checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                              error=(result.get('error') or '')[-1500:])
    summary['project_file_unchanged'] = Path(spec['project']).read_bytes() == project_bytes
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    ok = all(v.get('passed') and v.get('exit') == 0 for k, v in summary.items() if isinstance(v, dict))
    return 0 if ok and summary['project_file_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
