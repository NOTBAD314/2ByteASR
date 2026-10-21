"""Real-window check of math formulas in captions (Unicode level, 2026-10-16, ADR 0124).

Makes a 12-second synthetic video with the bundled ffmpeg and a project whose
captions contain ``$…$`` formulas, isolates all app data in a fresh tmp/
directory and runs the in-process `math-formulas` scenario
(twobyteasr/acceptance/math_formulas_audit.py) on a private Windows desktop.
Use --exe for a frozen candidate. Writes result.json, captures and exports.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXTS = [
    "这一段讲谢尔宾斯基三角形",
    r"这个三角形的面积是 $\frac{\sqrt{3}}{4}a^2$",
    r"对它积分：$\int_0^1 x^2\,dx = \frac{1}{3}$",
    r"维数 $\log_2 3 \approx 1.585$，门票 \$5",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    media = out / 'synthetic.mp4'
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'color=c=0x2f4f5f:s=1280x720:r=30:d=12',
                    '-f', 'lavfi', '-i', 'sine=frequency=330:duration=12',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)], check=True)
    sys.path.insert(0, str(ROOT))
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'builder')  # building the project never touches real data
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                                    save_project)
    from twobyteasr.subtitle_rules.math_text import caption_text
    cues = [StudioCue(f'c{index}', index * 3000 + 200, index * 3000 + 2800, text, speaker_id='S00')
            for index, text in enumerate(TEXTS)]
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=12000, width=1280, height=720),
                              cues=cues, speakers=[StudioSpeaker('S00', '主播')])
    path = save_project(project, out / 'project.2byteproj')
    expected = {cue.id: caption_text(cue.text) for cue in cues if caption_text(cue.text) != cue.text}
    spec = dict(project=str(path), cue_id='c2', texts=TEXTS, expected=expected)
    (out / 'input.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='math-formulas',
               TWOBYTEASR_STARTUP_PROJECT=str(path), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    result['process_exit'] = code
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(output=str(out), checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          error=(result.get('error') or '')[-1200:], exit=code), ensure_ascii=False, indent=1))
    return 0 if result.get('passed') and code == 0 and result.get('gui_shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
