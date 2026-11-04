"""Real-window check of 只重新识别这一段字幕 (2026-10-25).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``range-recognition``
acceptance scenario (``twobyteasr/acceptance/range_recognition_audit.py``):
recognize a clip, make the middle sentence wrong, set in/out, pick the
right-click entry, confirm, let the stretch be recognized again, check the
replacement and its undo.

The runner makes its own clip under ``--output``: three Chinese sentences read
by a Windows voice with pauses between them, in an MP4. Recognition runs on
the local models named by ``--models-combo`` (read-only links to ``--models``,
removed after the run). Nothing contacts the network.

    python -X utf8 scripts/verify_range_recognition_headed.py --output tmp/<new folder> \\
        --main-runtime <registered main runtime python> [--exe <frozen 2ByteASR.exe>]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
VOICE = 'Microsoft Huihui Desktop'
SENTENCES = {
    's1': '第一句保持不动。今天下午，我们在公园里看到一只小猫。',
    's2': '第二句需要重新识别。明天早上八点，火车从北京出发，中午到达上海。',
    's3': '第三句也保持不动。晚上我们一起去电影院看电影。',
}
WORDS = {'s1': ['公园', '小猫'], 's2': ['火车', '北京', '上海'], 's3': ['电影']}
GAP_S = 1.2
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


def _media(out: Path) -> dict:
    """Three sentences with pauses; returns the MP4 and each sentence's span (ms)."""
    folder = out / 'media'
    folder.mkdir()
    (folder / 'speak.ps1').write_text(SPEAK_PS1, 'utf-8-sig')
    pcm, spans, cursor = bytearray(), {}, GAP_S
    pause = b'\x00\x00' * int(16000 * GAP_S)
    for name, text in SENTENCES.items():
        (folder / f'{name}.txt').write_text(text, 'utf-8')
        spoken = folder / f'{name}.wav'
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(folder / 'speak.ps1'),
                        '-Out', str(spoken), '-TextFile', str(folder / f'{name}.txt'), '-Voice', VOICE], check=True)
        mono = folder / f'{name}-16k.wav'
        subprocess.run([str(_ffmpeg()), '-hide_banner', '-v', 'error', '-y', '-i', str(spoken), '-ac', '1', '-ar',
                        '16000', '-c:a', 'pcm_s16le', str(mono)], check=True)
        with wave.open(str(mono), 'rb') as clip:
            frames, seconds = clip.readframes(clip.getnframes()), clip.getnframes() / clip.getframerate()
        pcm += pause + frames
        spans[name] = [round(cursor * 1000), round((cursor + seconds) * 1000)]
        cursor += seconds + GAP_S
    pcm += pause
    speech = folder / 'speech.wav'
    with wave.open(str(speech), 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(bytes(pcm))
    seconds = len(pcm) / 32000
    clip = folder / 'three-sentences.mp4'
    subprocess.run([str(_ffmpeg()), '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'color=c=0x334455:s=640x360:r=25:d={seconds:.3f}', '-i', str(speech), '-map', '0:v', '-map',
                    '1:a', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                    '-b:a', '128k', '-shortest', str(clip)], check=True)
    return dict(media=str(clip), spans=spans, seconds=round(seconds, 3))


def _project(out: Path) -> str:
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    target = out / 'projects' / 'range' / 'range.2byteproj'
    target.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='range', duration_ms=0)), target)
    return str(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--models', type=Path, default=ROOT.parents[2] / 'models'
                        if (ROOT.parents[2] / 'models').is_dir() else ROOT / 'models')
    parser.add_argument('--models-combo', default='qwen_local,local,off',
                        help='primary,timeline,review backends for every recognition in the scenario')
    parser.add_argument('--main-python', type=Path, help='registered main runtime python (source runs)')
    parser.add_argument('--main-runtime', type=Path, help='real main runtime python via a venv shim')
    parser.add_argument('--timeout', type=int, default=2400)
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
    config.update(project=_project(out), words=WORDS, models=args.models_combo.split(','))
    from verify_multi_audio_tracks_headed import _link, _unlink
    model_root = Path(os.environ['2BYTEASR_MODEL_ROOT'])
    wanted = ('FireRedASR2-AED', 'FireRedVAD', 'Qwen3-ASR-1.7B', 'Qwen3-ForcedAligner-0.6B', 'spkrec-ecapa-voxceleb',
              'SenseVoiceSmall')
    links = _link((args.models.resolve() / name, model_root / name) for name in wanted)
    checkout = ROOT.parents[2]
    if (checkout / 'third_party').is_dir() and checkout != ROOT:
        links += _link((checkout / 'third_party' / name, ROOT / 'third_party' / name)
                       for name in ('FireRedASR2S',))
    try:
        local, roaming = out / 'local', out / 'roaming'
        local.mkdir()
        roaming.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
        env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
                   TWOBYTEASR_STARTUP_PROJECT=config['project'], TWOBYTEASR_TEST_ROOT=str(profile),
                   PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
                   TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='range-recognition',
                   TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
                   NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
                   TWOBYTEASR_RANGE_RECOGNITION=json.dumps(config, ensure_ascii=False))
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
