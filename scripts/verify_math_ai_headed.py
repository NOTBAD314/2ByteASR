"""Real-window check: AI features keep math formulas; a term library's 「给 AI 的说明」 (2026-10-16, ADR 0124).

Builds an isolated user-data folder with one term library and a project whose math switch is on, then runs
the `math-ai` scenario (twobyteasr/acceptance/math_ai_audit.py) in the real application on a private Windows
desktop. Only loopback connections are allowed; the AI service is a stand-in on 127.0.0.1; no paid call.
Use --exe for a packaged candidate.
"""
import argparse
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
TEXTS = [r'谢尔宾斯机三角形的面积是 $\frac{\sqrt{3}}{4}a^2$',
         r'它的维数是 $\log_2 3 \approx 1.585$',
         '最后一句没有公式']


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    removed = sorted(key for key in os.environ if re.search(r'(API_?KEY|_TOKEN|ACCESS_?KEY)', key, re.IGNORECASE))
    for key in removed:
        os.environ.pop(key)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core as legacy
    from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    from twobyteasr.math_text import STATE_KEY, state_value

    name = '数学科普'
    library = legacy.create_learned_content(name, create_new=True)
    legacy.add_learned_mapping(library, '谢尔宾斯基三角形', '谢尔宾斯基三角形', category='名词', origin='手动')
    legacy.add_learned_mapping(library, '谢尔宾斯机三角形', '谢尔宾斯基三角形', category='名词', origin='手动')
    folder = output / 'projects' / 'math-ai'
    folder.mkdir(parents=True)
    media = folder / 'math-ai.mp4'
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-y', '-v', 'error',
                    '-f', 'lavfi', '-i', 'color=c=0x2f4f5f:s=1280x720:r=30:d=12',
                    '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000:duration=12',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)], check=True)
    project = SubtitleProject(
        media=StudioMedia(path=str(media), display_name='数学公式与 AI', duration_ms=12_000, width=1280, height=720),
        cues=[StudioCue(f'c{i}', i * 3500 + 500, i * 3500 + 3000, text, speaker_id='S00')
              for i, text in enumerate(TEXTS)],
        speakers=[StudioSpeaker('S00', '主播')], glossary_ids=[library])
    project.studio_state[STATE_KEY] = state_value(True)
    path = save_project(project, folder / 'math-ai.2byteproj')
    (output / 'input.json').write_text(json.dumps(dict(project=str(path), library=library, library_name=name,
                                                       texts=TEXTS), ensure_ascii=False, indent=2), 'utf8')
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='math-ai',
               TWOBYTEASR_STARTUP_PROJECT=str(path),
               TWOBYTEASR_STARTUP_RAISE='1', TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SEEK_CACHE_ROOT=str(output / 'seek'), QT_QPA_PLATFORM='windows',
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    started = time.monotonic()
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=900)
    receipt = output / 'result.json'
    result = {}
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            result = json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    result['launcher_exit'] = code
    result['wall_s'] = round(time.monotonic() - started, 1)
    result['passed'] = bool(result.get('passed') and code == 0 and result.get('gui_shutdown'))
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                          error=(result.get('error') or '')[-1500:], launcher_exit=code,
                          screenshots=result.get('screenshots'), output=str(output)), ensure_ascii=False, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
