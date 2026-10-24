"""Real-window check: the home page asks which audio tracks to recognize (2026-10-24).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder, on the home page, and runs the
``home-audio-tracks`` acceptance scenario
(``twobyteasr/acceptance/home_audio_tracks_audit.py``).

The media are the ones of ``verify_multi_audio_tracks_headed.py`` (made under
``--output``): Windows voices reading different sentences, muxed as separate
audio streams of an MP4, an MKV with a subtitle stream between its audio
streams and a dub that starts 3 s late, plus a stereo and a 5.1 file.
Recognition runs on the local models named by ``--models-combo`` (read-only
links to ``--models``, removed after the run). Nothing contacts the network.

    python -X utf8 scripts/verify_home_audio_tracks_headed.py --output tmp/<new folder> \\
        --main-python <registered main runtime python> [--exe <frozen 2ByteASR.exe> --main-runtime <python>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from verify_multi_audio_tracks_headed import WORDS, _link, _media, _unlink  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--models', type=Path, default=ROOT.parents[2] / 'models'
                        if (ROOT.parents[2] / 'models').is_dir() else ROOT / 'models')
    parser.add_argument('--models-combo', default='qwen_local,local,off',
                        help='primary,timeline,review backends for every recognition in the scenario')
    parser.add_argument('--main-python', type=Path, help='registered main runtime python (source runs)')
    parser.add_argument('--main-runtime', type=Path, help='real main runtime python via a venv shim (frozen runs)')
    parser.add_argument('--timeout', type=int, default=4800)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    profile = out / 'profile'
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(profile)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    config = _media(out)
    config.update(words=WORDS, models=args.models_combo.split(','))
    # The acceptance runner wants its own copied project; Home never opens it.
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    startup = out / 'projects' / 'home' / 'home.2byteproj'
    startup.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='home', duration_ms=0)), startup)
    model_root = Path(os.environ['2BYTEASR_MODEL_ROOT'])
    wanted = ('FireRedASR2-AED', 'FireRedVAD', 'Qwen3-ASR-1.7B', 'Qwen3-ForcedAligner-0.6B', 'spkrec-ecapa-voxceleb',
              'MOSS-Transcribe-Diarize', 'SenseVoiceSmall')
    links = _link((args.models.resolve() / name, model_root / name) for name in wanted)
    # A worktree has no copy of the git-ignored model code FireRed and MOSS import.
    checkout = ROOT.parents[2]
    if (checkout / 'third_party').is_dir() and checkout != ROOT:
        links += _link((checkout / 'third_party' / name, ROOT / 'third_party' / name)
                       for name in ('FireRedASR2S', 'MOSS-Transcribe-Diarize'))
    try:
        local, roaming = out / 'local', out / 'roaming'
        local.mkdir()
        roaming.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
        env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
                   TWOBYTEASR_STARTUP_PROJECT=str(startup), TWOBYTEASR_TEST_ROOT=str(profile),
                   PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
                   TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='home-audio-tracks',
                   TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
                   NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
                   TWOBYTEASR_MULTI_AUDIO=json.dumps(config, ensure_ascii=False))
        for key in [k for k in env if k.lower() in {'http_proxy', 'https_proxy', 'no_proxy'} and not k.isupper()]:
            env.pop(key)  # one spelling per variable (the root launcher dies on duplicates)
        if args.main_runtime:
            from verify_ui_polish_headed import _runtime_shim
            from twobyteasr.system.runtime_registry import stable_runtime_root
            env['TWOBYTEASR_MAIN_PYTHON'] = str(_runtime_shim(args.main_runtime, Path(stable_runtime_root('main'))))
        elif args.main_python:
            env['TWOBYTEASR_MAIN_PYTHON'] = str(args.main_python)
        (out / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=1), 'utf-8')
        command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    finally:
        _unlink(links)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0 and bool(result.get('gui_shutdown')), exit=code,
                   shutdown=result.get('gui_shutdown'), executable=result.get('executable'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   failed=[c for c in result.get('checks', []) if not c['passed']],
                   dialogs=result.get('dialogs'), errors=[e[-1500:] for e in result.get('errors', [])])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
