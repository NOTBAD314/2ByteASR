# SPDX-License-Identifier: GPL-3.0-only
"""Exercise cursor splitting through the installed Apple Silicon application."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_blank_project_macos import audit_boundary, blank_environment


def prepare_fixture(output, ffmpeg):
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    media = output/'caret-fixture.mp4'
    with (output/'sample-media.log').open('wb') as stream:
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=0x283d4e:s=960x540:r=25:d=16', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
            '-t', '16', '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            '-threads', '2', str(media)], check=True, timeout=90, stdout=stream, stderr=stream)
    texts = ['今日はここまで。また明日ね。', 'Hello world.  See you tomorrow.',
             '你好，世界。明天见。', '😀Cafe\u0301 家庭👨‍👩‍👧‍👦 继续']
    cues = [StudioCue(f'cue-{i}', i*3000, i*3000+2800, texts[i % 4]) for i in range(7000)]
    project = SubtitleProject(StudioMedia(str(media), duration_ms=21_000_000,
                                        width=960, height=540), cues=cues)
    project.asr_evidence['aligned'] = dict(words=[dict(text=char, start_ms=i*200, end_ms=i*200+100)
                                               for i, char in enumerate(texts[0])])
    cues[0].evidence_refs = ['aligned']
    return save_project(project, output/'caret-fixture.2byteproj')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon macOS is required')
    output, invoker = audit_boundary(args.output)
    app = args.app.resolve()
    executable = app/'Contents/MacOS/2ByteASR'
    if app.name != '2ByteASR.app' or not executable.is_file():
        raise ValueError('An installed 2ByteASR.app is required')
    ffmpeg = app/'Contents/Resources/tools/ffmpeg/bin/ffmpeg'
    if not ffmpeg.is_file():
        ffmpeg = app/'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    output.mkdir(parents=True)
    summary = dict(passed=False, expected_executable=str(executable),
                   scope='Native installed Mac app; Qt input; 7000 cues, 5h50m timeline, 16s synthetic media')
    process = None
    try:
        target = prepare_fixture(output, ffmpeg)
        env = blank_environment(output, invoker, target)
        env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='macos-caption-caret-split',
                   EDIT_SAVE_PROJECT=str(target), EDIT_SAVE_PART='caret', CARET_SPLIT_PROJECT=str(target))
        with (output/'caret-split.log').open('wb') as stream:
            process = subprocess.Popen([str(executable), str(target)], cwd=invoker, env=env,
                                       stdout=stream, stderr=stream, start_new_session=True)
            summary['launcher_exit'] = process.wait(timeout=600)
        result = json.loads((output/'result.json').read_text('utf8'))
        identity = json.loads((output/'local/2ByteASR/logs/build_identity.json').read_text('utf8'))
        startup = json.loads((output/'startup-project-result.json').read_text('utf8'))
        checks = result.get('checks', {})
        summary.update(application_result=result, identity=identity, startup=startup, checks=len(checks))
        summary['passed'] = bool(summary['launcher_exit'] == 0 and result.get('passed') is True
            and result.get('gui_shutdown') is True and len(checks) >= 49 and all(checks.values())
            and identity.get('packaged') is True and startup.get('passed') is True
            and Path(identity.get('executable_path', '')).resolve() == executable)
    except Exception:
        summary['error'] = traceback.format_exc()
    finally:
        from scripts.macos_desktop_smoke import preserve_diagnostics
        preserve_diagnostics(output)
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
            except ProcessLookupError:
                pass
        (output/'caret-split-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', 'utf8')
    print(json.dumps(dict(passed=summary['passed'], checks=summary.get('checks'))))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
