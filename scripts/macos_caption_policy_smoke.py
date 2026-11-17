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
        'speaker-board', 'timeline-cue-pill', 'vm2-model-settings', 'workshop-columns', 'multilingual-terms', 'vm2-onboarding', 'bunny-chat', 'editor-download', 'english-track-loudness', 'task-candy', 'usage-candy', 'bunny-harness', 'tutorial-centre', 'ai-escalation', 'glossary-conflicts', 'bunny-112', 'editor-review', 'playhead-center', 'home-layout'], required=True)
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
        from scripts.macos_release110_fixture import prepare_fixture
        fixture_scenario = {'bunny-harness': 'editor-download', 'tutorial-centre': 'editor-download', 'ai-escalation': 'task-candy', 'bunny-112':'editor-download', 'editor-review':'editor-download', 'playhead-center':'editor-download'}.get(args.scenario, args.scenario)
        target = prepare_fixture(args.app.resolve(), output, fixture_scenario, target)
        if args.scenario == 'ai-escalation':
            from twobyteasr.projects.studio_project import load_project, StudioCue
            fixture = load_project(target)
            fixture.cues = [StudioCue(f'cue-{i}', i*1800, i*1800+1600, f'这是第{i}条字幕，正在检查加载响应。') for i in range(12)]
            fixture.media.duration_ms = 21600
            (output/'p12').mkdir()
            save_project(fixture, output/'p12/project.2byteproj')
        if args.scenario == 'editor-review':
            from twobyteasr.projects.studio_project import load_project, StudioCue
            from twobyteasr.subtitle_rules import subtitle_translation as st
            fixture=load_project(target)
            fixture.cues=[StudioCue('a',0,5000,'她打不出什么东西'),StudioCue('b',5100,10000,'他告诉她们今天晚点来，其他人弹吉他。')]
            translation='她们会来吗'
            fixture.generation_metadata.update(translations={'a':translation},translation_records=dict(version=1,target='zh',records={'a':st._record(translation,fixture.cues[0].text,origin=st.ORIGIN_MANUAL)},history=[]))
            save_project(fixture,target)
        env = blank_environment(output, invoker, target)
        if args.scenario == 'editor-download':
            env.update(TWOBYTEASR_EDITOR_BACKGROUND_AUDIT='1', TWOBYTEASR_BUNNY_AGENT_AUDIT='1', TWOBYTEASR_MOTION_TIMELINE_AUDIT='1')
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = 'vm2-model-settings' if args.scenario in {'workshop-columns', 'vm2-onboarding'} else args.scenario
        if args.scenario in {'bunny-harness', 'tutorial-centre'}:
            env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = 'editor-download'
            env['TWOBYTEASR_EDITOR_BACKGROUND_AUDIT'] = '1'
        if args.scenario == 'bunny-harness':
            env.update(TWOBYTEASR_BUNNY_HARNESS_AUDIT='1', TWOBYTEASR_BUNNY_AGENT_AUDIT='1', TWOBYTEASR_BUNNY_VISION_OVERLAY_AUDIT='1', TWOBYTEASR_MOTION_TIMELINE_AUDIT='1')
        if args.scenario == 'tutorial-centre':
            env['TWOBYTEASR_TUTORIAL_CENTRE_AUDIT'] = '1'
        if args.scenario == 'ai-escalation':
            env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='theme-loading', TWOBYTEASR_AI_ESCALATION_AUDIT='1')
        if args.scenario in {'bunny-112','playhead-center'}:
            env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-download',TWOBYTEASR_EDITOR_BACKGROUND_AUDIT='1')
        if args.scenario == 'bunny-112':
            env.update(TWOBYTEASR_BUNNY_UNIVERSAL_AUDIT='1',TWOBYTEASR_BUNNY_HARNESS_AUDIT='1',TWOBYTEASR_BUNNY_AGENT_AUDIT='1',TWOBYTEASR_BUNNY_VISION_OVERLAY_AUDIT='1',TWOBYTEASR_BUNNY_PERSONA_PICTURE_AUDIT='1',TWOBYTEASR_BUNNY_HARNESS_P2_AUDIT='1',TWOBYTEASR_MOTION_TIMELINE_AUDIT='1')
        if args.scenario == 'playhead-center':
            env['TWOBYTEASR_PLAYHEAD_CENTER_AUDIT']='1'
        if args.scenario == 'editor-review':
            env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-download',TWOBYTEASR_EDITOR_REVIEW_INTERACTION_AUDIT='1')
        if args.scenario == 'home-layout':
            env['TWOBYTEASR_ACCEPTANCE_SCENARIO']='home-plan-zoom'
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
        receipt = 'conflict-result.json' if args.scenario == 'glossary-conflicts' else 'multilingual-terms.json' if args.scenario == 'multilingual-terms' else 'result.json'
        audit = json.loads((output / receipt).read_text('utf8'))
        identity = json.loads((output / 'local/2ByteASR/logs/build_identity.json').read_text('utf8'))
        checks = audit.get('checks', [])
        expected_checks = {'stable-captions': 50, 'chinese-complete-expression': 17,
            'speaker-board': 20, 'timeline-cue-pill': 22, 'vm2-model-settings': 100, 'workshop-columns': 100, 'multilingual-terms': 20, 'vm2-onboarding': 100, 'bunny-chat': 109, 'editor-download': 126, 'english-track-loudness': 37, 'task-candy': 25, 'usage-candy': 26, 'bunny-harness': 150, 'tutorial-centre': 300, 'ai-escalation': 27, 'glossary-conflicts': 20, 'bunny-112': 259, 'editor-review': 100, 'playhead-center': 18, 'home-layout': 70}[args.scenario]
        result.update(application_result=audit, identity=identity, checks=len(checks))
        result['passed'] = (result['process_exit'] == 0 and audit.get('passed') is True
            and len(checks) >= expected_checks and (all(checks.values()) if isinstance(checks, dict) else all(row['passed'] for row in checks))
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
