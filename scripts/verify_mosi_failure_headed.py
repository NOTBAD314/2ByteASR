"""MOSS Pro cloud: a split task whose second request waits long and then fails, in the real window (2026-10-23).

User report: a 96-minute task went to MOSI as two requests; the progress card
showed "已返回批次 1 / 2 · 云端识别中 · 最近回应 0 秒前" for 24 minutes, then the
task failed with "上次提交的云端识别任务已结束但没有成功" and a long block of
result JSON, and every retry failed in 3 seconds without saying why.

Prepares 61+ minutes of synthetic speech (three MOSI requests) in an isolated
profile and runs ``twobyteasr/acceptance/mosi_failure_audit.py`` inside the
real app (source, or the frozen EXE with ``--exe``, which uploads through its
own ``--asr-api-worker``) on a private desktop. MOSI is a loopback stand-in:
no key, no network, no paid call. The steps and checks are in the audit.

``--scenario mosi-blocked`` (2026-10-24) runs
``twobyteasr/acceptance/mosi_blocked_audit.py`` instead: MOSI's content safety
review stops the second request; the task finishes with a gap, and 切成小段再交
MOSI sends it again in pieces. ``--fill-model sensevoice --main-runtime <python>``
links the real SenseVoice model (read-only junction, removed afterwards) and the
main runtime into the isolated profile, so the gap is filled locally.

``--scenario mosi-timing`` (2026-10-25) runs
``twobyteasr/acceptance/mosi_timing_audit.py``: MOSI returns sentences timed
past a request's audio or with swapped times; the task finishes with them
clipped or left out, and 查看原因 says where and how many.

usage: python scripts/verify_mosi_failure_headed.py --output tmp/<new dir> [--minutes 61.5] [--exe <frozen>]
                                                    [--scenario mosi-failure|mosi-blocked|mosi-timing]
                                                    [--fill-model sensevoice --main-runtime <python>]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def build_media(output: Path, minutes: float) -> Path:
    """Synthetic speech looped past MOSI's 60-minute limit (audio only, quick to encode)."""
    from timing_benchmark import build_synthetic
    reference = json.loads(build_synthetic(output / 'synthetic').read_text(encoding='utf-8'))
    ffmpeg = ROOT / 'tools' / 'ffmpeg' / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    media = output / 'media' / 'mosi-two-requests.m4a'
    media.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-stream_loop', '-1', '-i', reference['audio'],
                    '-t', str(int(minutes * 60)), '-ac', '1', '-c:a', 'aac', '-b:a', '48k', str(media)], check=True)
    return media


JUNCTION = 0xA0000003


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
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--minutes', type=float, default=61.5)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scenario', choices=('mosi-failure', 'mosi-blocked', 'mosi-timing'), default='mosi-failure')
    parser.add_argument('--fill-model', choices=('sensevoice',))
    parser.add_argument('--main-runtime', type=Path, help='real main runtime python (read through a venv shim)')
    parser.add_argument('--models', type=Path, default=ROOT.parents[2] / 'models'
                        if (ROOT.parents[2] / 'models').is_dir() else ROOT / 'models')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    media = build_media(output, args.minutes)
    for key in [key for key in os.environ if re.search(r'(API_?KEY|_TOKEN|ACCESS_?KEY)', key, re.IGNORECASE)]:
        os.environ.pop(key)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    settings = copy.deepcopy(settings_module.DEFAULT_SETTINGS)
    settings['switches'].update(enable_ai_polish=False, use_ai_grouping=False)
    settings['models']['speaker_source'] = 'single'
    settings_path = settings_module.project_settings_path()  # <test root>/config in an isolated run
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'delivery.json').write_text(json.dumps(dict(media=str(media), minutes=args.minutes,
                                                          fill_model=args.fill_model or ''),
                                                     ensure_ascii=False, indent=2), 'utf-8')
    links = []
    if args.fill_model:
        # Only the model this check needs; the links are removed below.
        model_root = Path(os.environ['2BYTEASR_MODEL_ROOT'])
        links = _link([(args.models.resolve() / 'SenseVoiceSmall', model_root / 'SenseVoiceSmall')])
    entry = save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), output / 'entry.2byteproj')
    env = os.environ.copy()
    # One spelling per variable: the root 2ByteASR.exe launcher (.NET) refuses an
    # environment holding both HTTP_PROXY and http_proxy and never starts the app.
    for key in [key for key in env if key.startswith('TWOBYTEASR_STARTUP_') or key.lower() in
                {'http_proxy', 'https_proxy', 'no_proxy', 'all_proxy'}]:
        env.pop(key)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO=args.scenario,
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
               CUDA_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               NO_PROXY='127.0.0.1,localhost')
    if args.scale != '1':
        env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96',
                   QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough')
    if args.main_runtime:
        # The queue only accepts a main interpreter inside the app's own runtime
        # folder (under the test root: the profile); a small venv reads the real one.
        from verify_ui_polish_headed import _runtime_shim
        from twobyteasr.system.runtime_registry import stable_runtime_root
        env['TWOBYTEASR_MAIN_PYTHON'] = str(_runtime_shim(args.main_runtime, Path(stable_runtime_root('main'))))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    started = time.monotonic()
    try:
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=2400)
    finally:
        _unlink(links)
    result_path = output / 'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else {}
    passed = bool(code == 0 and result.get('passed') and result.get('gui_shutdown'))
    print(json.dumps(dict(passed=passed, exit_code=code, output=str(output), wall_s=round(time.monotonic() - started, 1),
                          error=result.get('error'), failed=[c['name'] for c in result.get('checks', []) if not c['passed']],
                          checks=len(result.get('checks', [])), executable=result.get('executable')), ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
