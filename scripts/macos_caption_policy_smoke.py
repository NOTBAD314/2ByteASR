"""Run caption placement and Chinese grouping through an installed native app."""
from pathlib import Path
import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_blank_project_macos import audit_boundary, blank_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario', choices=['stable-captions', 'chinese-complete-expression',
        'speaker-board', 'timeline-cue-pill', 'vm2-model-settings', 'workshop-columns', 'multilingual-terms', 'vm2-onboarding'], required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon macOS is required')
    output, invoker = audit_boundary(args.output)
    executable = args.app.resolve() / 'Contents/MacOS/2ByteASR'
    if not executable.is_file():
        raise ValueError('An installed 2ByteASR.app is required')
    output.mkdir(parents=True)
    result = dict(passed=False, scenario=args.scenario, expected_executable=str(executable))
    process = None
    try:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
        target = save_project(SubtitleProject(StudioMedia('')), output / 'startup.2byteproj')
        if args.scenario in {'speaker-board', 'timeline-cue-pill'}:
            ffmpeg = args.app.resolve() / 'Contents/Resources/tools/ffmpeg/bin/ffmpeg'
            if not ffmpeg.is_file():
                ffmpeg = args.app.resolve() / 'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
            media = output / 'fixture.mp4'
            with (output / 'sample-media.log').open('wb') as stream:
                subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=0x252131:size=1280x720:rate=30:duration=24', '-f', 'lavfi', '-i',
                    'anullsrc=r=48000:cl=stereo', '-t', '24', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(media)],
                    check=True, timeout=90, stdout=stream, stderr=stream)
            if args.scenario == 'speaker-board':
                from scripts.verify_speaker_board_headed import project
                fixture = project()
                fixture.media.path = str(media)
            else:
                from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker
                fixture = SubtitleProject(StudioMedia(str(media), duration_ms=24000, width=1280, height=720),
                    speakers=[StudioSpeaker('S0', '主播')],
                    cues=[StudioCue('a', 10000, 13000, '第一句字幕', 'S0'),
                          StudioCue('b', 13000, 16000, '第二句字幕', 'S0'),
                          StudioCue('c', 17000, 20000, '第三句字幕', 'S0')])
                fixture.render_settings['fps'] = 30
            save_project(fixture, output / 'fixture.2byteproj')
        env = blank_environment(output, invoker, target)
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = 'vm2-model-settings' if args.scenario in {'workshop-columns', 'vm2-onboarding'} else args.scenario
        if args.scenario == 'vm2-onboarding':
            env['TWOBYTEASR_VM2_ONBOARDING_ONLY'] = '1'
        if args.scenario == 'workshop-columns':
            env['TWOBYTEASR_WORKSHOP_COLUMNS_ONLY'] = '1'
        with (output / 'caption-policy.log').open('wb') as stream:
            # The guard project is not a second CLI navigation request. Each
            # scene opens its own fixture through the normal MainWindow API.
            process = subprocess.Popen([str(executable)], cwd=invoker, env=env,
                stdout=stream, stderr=stream, start_new_session=True)
            result['process_exit'] = process.wait(timeout=660)
        receipt = 'multilingual-terms.json' if args.scenario == 'multilingual-terms' else 'result.json'
        audit = json.loads((output / receipt).read_text('utf8'))
        identity = json.loads((output / 'local/2ByteASR/logs/build_identity.json').read_text('utf8'))
        checks = audit.get('checks', [])
        expected_checks = {'stable-captions': 50, 'chinese-complete-expression': 17,
            'speaker-board': 20, 'timeline-cue-pill': 22, 'vm2-model-settings': 100, 'workshop-columns': 100, 'multilingual-terms': 20, 'vm2-onboarding': 100}[args.scenario]
        result.update(application_result=audit, identity=identity, checks=len(checks))
        result['passed'] = (result['process_exit'] == 0 and audit.get('passed') is True
            and len(checks) >= expected_checks and all(row['passed'] for row in checks)
            and identity.get('packaged') is True
            and Path(identity.get('executable_path', '')).resolve() == executable)
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        from scripts.macos_desktop_smoke import preserve_diagnostics
        preserve_diagnostics(output)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
        (output / 'caption-policy-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=result.get('checks'))))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
