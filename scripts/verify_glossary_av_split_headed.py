"""Real-window check of terms with symbols, deleting built-in libraries and the
workbench source preview with picture / sound drags (2026-10-25).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``glossary-av-split``
acceptance scenario (``twobyteasr/acceptance/glossary_av_split_audit.py``).
The runner makes its own media under ``--output`` with FFmpeg: a 12 s main
MP4, a 5 s second MP4 and a 6 s WAV (tones over coloured frames). No models,
nothing contacts the network.

    python -X utf8 scripts/verify_glossary_av_split_headed.py --output tmp/<new folder> [--exe <2ByteASR.exe>]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def _ffmpeg():
    return ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'


def _media(out: Path) -> dict:
    folder = out / 'media'
    folder.mkdir()
    made = {}
    for key, name, seconds, colour, tone in (('main', 'main-recording.mp4', 12, '0x334455', 440),
                                             ('clip', 'reaction.mp4', 5, '0x885522', 880)):
        target = folder / name
        subprocess.run([str(_ffmpeg()), '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        f'testsrc2=s=640x360:r=25:d={seconds}', '-f', 'lavfi', '-i',
                        f'sine=frequency={tone}:sample_rate=48000:duration={seconds}', '-vf',
                        f'drawbox=c={colour}@0.5:t=fill', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt',
                        'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest', str(target)], check=True)
        made[key] = str(target)
    song = folder / 'bgm-song.wav'
    subprocess.run([str(_ffmpeg()), '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'sine=frequency=660:sample_rate=48000:duration=6', '-c:a', 'pcm_s16le', str(song)], check=True)
    made['song'] = str(song)
    return made


def _project(out: Path, name: str = 'av') -> str:
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    target = out / 'projects' / name / f'{name}.2byteproj'
    target.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name=name, duration_ms=0)), target)
    return str(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
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
    config['project'] = _project(out)
    config['other_project'] = _project(out, 'other')
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=config['project'], TWOBYTEASR_TEST_ROOT=str(profile),
               PYTHONUTF8='1', PYTHONFAULTHANDLER='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-av-split',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               TWOBYTEASR_GLOSSARY_AV=json.dumps(config, ensure_ascii=False))
    (out / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=1), 'utf-8')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
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
