"""Real-window check of multi-track import and the recognition track picker (2026-10-24).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``multi-audio-tracks``
acceptance scenario (``twobyteasr/acceptance/multi_audio_tracks_audit.py``).

The runner makes its own media under ``--output``: three sentences read by
Windows voices (two Chinese, one English) muxed as separate audio streams —
an MP4 with two tracks, an MKV with a subtitle stream between its audio
streams and a dub that starts 3 s late, a stereo and a 5.1 file with one
track each, and a file without audio. Recognition runs on the local models
named by ``--models-combo`` (read-only links to ``--models``, removed after
the run). Nothing contacts the network.

    python -X utf8 scripts/verify_multi_audio_tracks_headed.py --output tmp/<new folder> \\
        --main-python <registered main runtime python> [--exe <frozen 2ByteASR.exe>]
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
JUNCTION = 0xA0000003
SENTENCES = {
    'track1': ('Microsoft Huihui Desktop', '第一条音轨。今天下午，我们在公园里看到一只橘色的小猫，它躺在大树下面睡觉。'),
    'track2': ('Microsoft Huihui Desktop', '第二条音轨。明天早上八点，火车从北京出发，中午到达上海火车站。'),
    'track3': ('Microsoft Zira Desktop', 'This is the third audio track. The quick brown fox jumps over the lazy dog.'),
}
WORDS = {'track1': ['公园', '小猫', '大树', '睡觉'], 'track2': ['火车', '北京', '上海', '八点'],
         'track3': ['fox', 'dog']}
SPEAK_PS1 = r'''param([string]$Out, [string]$TextFile, [string]$Voice)
Add-Type -AssemblyName System.Speech
$text = Get-Content -Encoding UTF8 -Raw $TextFile
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice($Voice)
$synth.SetOutputToWaveFile($Out)
$synth.Speak($text)
$synth.Dispose()
'''


def _ffmpeg():
    return ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'


def _onset_ms(path: Path) -> int:
    import numpy as np
    raw = subprocess.run([str(_ffmpeg()), '-v', 'error', '-i', str(path), '-ac', '1', '-ar', '16000', '-f', 's16le', '-'],
                         capture_output=True, check=True).stdout
    data = np.frombuffer(raw, dtype='<i2').astype(np.float32)
    env = np.abs(data[: len(data) // 160 * 160]).reshape(-1, 160).max(axis=1)
    return int(np.argmax(env > 1500)) * 10


def _media(out: Path) -> dict:
    folder = out / 'media'
    folder.mkdir()
    (folder / 'speak.ps1').write_text(SPEAK_PS1, 'utf-8-sig')
    refs = {}
    for name, (voice, text) in SENTENCES.items():
        (folder / f'{name}.txt').write_text(text, 'utf-8')
        target = folder / f'{name}.wav'
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(folder / 'speak.ps1'),
                        '-Out', str(target), '-TextFile', str(folder / f'{name}.txt'), '-Voice', voice], check=True)
        refs[name] = str(target)
    ff = [str(_ffmpeg()), '-hide_banner', '-v', 'error', '-y']
    video = ['-f', 'lavfi', '-i', 'color=c=0x334455:s=640x360:r=25:d=16']
    h264 = ['-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p']
    mp4 = folder / 'two-tracks.mp4'
    subprocess.run(ff + video + ['-i', refs['track1'], '-i', refs['track2'], '-filter_complex',
                   '[1:a]adelay=1000|1000,apad,atrim=0:16,aformat=channel_layouts=stereo[a1];'
                   '[2:a]adelay=1000|1000,apad,atrim=0:16,aformat=channel_layouts=stereo[a2]',
                   '-map', '0:v', '-map', '[a1]', '-map', '[a2]', *h264, '-c:a', 'aac', '-b:a', '128k',
                   '-metadata:s:a:0', 'title=中文原音', '-metadata:s:a:0', 'language=chi',
                   '-metadata:s:a:1', 'title=第二配音', '-metadata:s:a:1', 'language=chi',
                   '-disposition:a:0', 'default', '-disposition:a:1', '0', str(mp4)], check=True)
    srt = folder / 'embedded.srt'
    srt.write_text('1\n00:00:01,000 --> 00:00:03,000\nembedded subtitle\n', 'utf-8')
    mkv = folder / 'three-tracks-subs.mkv'
    subprocess.run(ff + video + ['-i', refs['track1'], '-i', str(srt), '-itsoffset', '3', '-i', refs['track2'],
                   '-i', refs['track3'], '-map', '0:v', '-map', '1:a', '-map', '2:s', '-map', '3:a', '-map', '4:a',
                   *h264, '-c:a:0', 'aac', '-ac:a:0', '2', '-c:a:1', 'aac', '-ac:a:1', '2', '-c:a:2', 'aac',
                   '-ac:a:2', '1', '-c:s', 'srt', '-metadata:s:a:0', 'title=日语原音', '-metadata:s:a:0', 'language=jpn',
                   '-metadata:s:a:1', 'title=中文配音', '-metadata:s:a:1', 'language=chi',
                   '-disposition:a:0', 'default', '-disposition:a:1', '0', '-disposition:a:2', '0', '-t', '16',
                   str(mkv)], check=True)
    stereo, surround, silent = folder / 'stereo-single.mp4', folder / 'surround-51.mkv', folder / 'no-audio.mp4'
    short = ['-f', 'lavfi', '-i', 'color=c=0x445533:s=640x360:r=25:d=8']
    subprocess.run(ff + short + ['-i', refs['track1'], '-map', '0:v', '-map', '1:a', *h264, '-c:a', 'aac', '-ac', '2',
                   '-shortest', str(stereo)], check=True)
    subprocess.run(ff + short + ['-i', refs['track1'], '-map', '0:v', '-map', '1:a', *h264, '-c:a', 'aac', '-af',
                   'pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0', '-shortest', str(surround)], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'color=c=0x222222:s=640x360:r=25:d=5', *h264, str(silent)], check=True)
    return dict(media=dict(mp4=str(mp4), mkv=str(mkv), stereo=str(stereo), surround=str(surround), silent=str(silent)),
                references=refs, track1_speech_start_ms=_onset_ms(Path(refs['track1'])),
                track2_speech_start_ms=_onset_ms(Path(refs['track2'])))


def _projects(out: Path) -> dict:
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    paths = {}
    for name in ('mp4', 'mkv', 'stereo', 'surround', 'silent'):
        target = out / 'projects' / name / f'{name}.2byteproj'
        target.parent.mkdir(parents=True)
        save_project(SubtitleProject(media=StudioMedia(path='', display_name=name, duration_ms=0)), target)
        paths[name] = str(target)
    return paths


def _link(pairs) -> list[Path]:
    links = []
    for target, link in pairs:
        if Path(target).is_dir() and not Path(link).exists():
            Path(link).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
            links.append(Path(link))
    return links


def _unlink(links) -> None:
    for link in links:
        try:
            if getattr(os.lstat(link), 'st_reparse_tag', 0) == JUNCTION:
                os.rmdir(link)  # the link only; the installed model is untouched
        except FileNotFoundError:
            pass


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
    parser.add_argument('--moss-python', type=Path)
    parser.add_argument('--timeout', type=int, default=3600)
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
    config.update(projects=_projects(out), words=WORDS, models=args.models_combo.split(','))
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
                   TWOBYTEASR_STARTUP_PROJECT=config['projects']['mp4'], TWOBYTEASR_TEST_ROOT=str(profile),
                   PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
                   TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='multi-audio-tracks',
                   TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
                   NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
                   TWOBYTEASR_MULTI_AUDIO=json.dumps(config, ensure_ascii=False))
        if args.main_runtime:
            # The queue's environment check only accepts interpreters inside the
            # app's own runtime folder; under the test root that is the profile,
            # so the small venv that reads the real runtime goes to the stable root.
            from verify_ui_polish_headed import _runtime_shim
            from twobyteasr.system.runtime_registry import stable_runtime_root
            env['TWOBYTEASR_MAIN_PYTHON'] = str(_runtime_shim(args.main_runtime, Path(stable_runtime_root('main'))))
        elif args.main_python:
            env['TWOBYTEASR_MAIN_PYTHON'] = str(args.main_python)
        if args.moss_python:
            env['TWOBYTEASR_MOSS_PYTHON'] = str(args.moss_python)
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
