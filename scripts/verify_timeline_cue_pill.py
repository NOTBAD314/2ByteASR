"""Run the normal application on a private desktop to check the 当前字幕 pill."""
from pathlib import Path
import argparse, json, os, subprocess, sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args(); out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'tmp') or out.exists():
        parser.error('fresh output under tmp required')
    out.mkdir(parents=True); os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project
    media = out / 'fixture.mp4'
    subprocess.run([str(ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=24',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=24000, width=1280, height=720),
                              speakers=[StudioSpeaker('S0', '主播')],
                              cues=[StudioCue('a', 10000, 13000, '第一句字幕', 'S0'),
                                    StudioCue('b', 13000, 16000, '第二句字幕', 'S0'),
                                    StudioCue('c', 17000, 20000, '第三句字幕', 'S0')])
    project.render_settings['fps'] = 30
    fixture = out / 'fixture.2byteproj'; save_project(project, fixture)
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='windows', TWOBYTEASR_ACCEPTANCE_SCENARIO='timeline-cue-pill',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_STARTUP_PROJECT=str(fixture),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'), PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for name in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):
        env.pop(name, None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-X', 'utf8', str(ROOT / 'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=out, timeout=300, receipt=out / 'result.json')
    result = json.loads((out / 'result.json').read_text('utf8')) if (out / 'result.json').is_file() else {}
    print(json.dumps(dict(output=str(out), exit=code, passed=result.get('passed'),
                          checks=len(result.get('checks', [])), error=result.get('error')), ensure_ascii=False))
    return 0 if code == 0 and result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
