# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the shared E30/save audit in the actual installed native Mac app."""
from __future__ import annotations

import argparse
from dataclasses import asdict
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


def prepare_fixture(output: Path, ffmpeg: Path, *, full_recording=False) -> Path:
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.acceptance.studio_search_fixture import make_project
    from twobyteasr.media.media_service import MediaService
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    from twobyteasr.timeline.studio_edit_sequence import persist_sequence, sequence_of

    media = output/'匿名・编辑保存.mp4'
    if full_recording:
        video_input = 'color=c=0x2a3344:s=640x360:r=1:d=21600'
        audio_input = 'sine=frequency=440:sample_rate=8000:duration=21600'
        duration = '21600'
        audio_options = ['-b:a', '24k', '-ac', '1']
        timeout = 300
    else:
        video_input = 'testsrc2=s=640x360:r=25:d=215'
        audio_input = 'anullsrc=r=48000:cl=stereo'
        duration = '215'
        audio_options = []
        timeout = 180
    with (output/'sample-media.log').open('wb') as stream:
        subprocess.run([str(ffmpeg), '-v', 'warning', '-f', 'lavfi', '-i', video_input,
                        '-f', 'lavfi', '-i', audio_input, '-t', duration, '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-crf', '32', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', *audio_options, str(media)], check=True, timeout=timeout,
                       stdout=stream, stderr=subprocess.STDOUT)
    service = MediaService(ffmpeg_path=ffmpeg, ffprobe_path=ffmpeg.with_name('ffprobe'+ffmpeg.suffix),
                           cache_root=output/'metadata-cache')
    metadata = service.metadata(media)
    project = make_project()
    if full_recording:
        project = SubtitleProject(StudioMedia(str(media), duration_ms=metadata.duration_ms,
            fingerprint=metadata.fingerprint, width=metadata.width, height=metadata.height),
            speakers=project.speakers, cues=project.cues, generation_metadata=project.generation_metadata,
            asr_evidence=project.asr_evidence)
        project.validate()
    for index, cue in enumerate(project.cues):
        cue.evidence_refs = [f'segment:{index}']
    old_path = project.media.path
    project.media.path = str(media)
    project.media.fingerprint = metadata.fingerprint
    project.media.width, project.media.height = metadata.width, metadata.height
    for asset in project.media_pool:
        if asset.canonical_source == old_path:
            asset.canonical_source = str(media)
            asset.fingerprint = metadata.fingerprint
            asset.video_metadata = asdict(metadata)
            asset.offline = False
    sequence = sequence_of(project)
    sequence.source_path = str(media)
    for segment in sequence.segments:
        if segment.source_path == old_path:
            segment.source_path = str(media)
    persist_sequence(project)
    target = output/'anonymous.2byteproj'
    save_project(project, target, compact=True)
    (output/'fixture-info.json').write_text(json.dumps(dict(full_recording=full_recording,
        cue_count=len(project.cues), media_duration_ms=metadata.duration_ms,
        project_duration_ms=project.media.duration_ms, per_cue_source_references=True,
        generated_media=True), indent=2), 'utf8')
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--part', choices=('edits', 'saves', 'waveform', 'waveform-full'), default='edits')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon macOS is required')
    output, invoker = audit_boundary(args.output)
    app = args.app.resolve()
    executable = app/'Contents/MacOS/2ByteASR'
    if app.name != '2ByteASR.app' or not executable.is_file():
        raise ValueError('--app must identify an actual frozen 2ByteASR.app')
    ffmpeg = app/'Contents/Resources/tools/ffmpeg/bin/ffmpeg'
    if not ffmpeg.is_file():
        ffmpeg = app/'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    output.mkdir(parents=True)
    summary = dict(passed=False, expected_executable=str(executable),
                   scope='Native installed app, synthetic Qt input, anonymous 5555-cue fixture',
                   part=args.part, fixture_media_seconds=215, fixture_timeline_seconds=18325,
                   physical_input_latency_measured=False)
    process = None
    try:
        target = prepare_fixture(output, ffmpeg, full_recording=args.part == 'waveform-full')
        summary['fixture'] = json.loads((output/'fixture-info.json').read_text('utf8'))
        summary.update(fixture_media_seconds=summary['fixture']['media_duration_ms']/1000,
                       fixture_timeline_seconds=summary['fixture']['project_duration_ms']/1000)
        env = blank_environment(output, invoker, target)
        scenario = 'macos-waveform-stability' if args.part in {'waveform', 'waveform-full'} else 'macos-edit-save'
        env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO=scenario, EDIT_SAVE_PROJECT=str(target),
                   EDIT_SAVE_PART=args.part, WAVEFORM_FULL_PROFILE='0')
        for folder in ('local', 'roaming', 'temp'):
            (output/folder).mkdir(exist_ok=True)
        with (output/'edit-save.log').open('wb') as stream:
            process = subprocess.Popen([str(executable), str(target)], env=env, cwd=invoker,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            summary['launcher_exit'] = process.wait(timeout=900)
        result = json.loads((output/'result.json').read_text('utf8'))
        identity = json.loads((output/'local/2ByteASR/logs/build_identity.json').read_text('utf8'))
        startup = json.loads((output/'startup-project-result.json').read_text('utf8'))
        checks = result.get('checks', {})
        summary.update(application_result=result, checks=len(checks), identity=identity, startup=startup)
        common_passed = (summary['launcher_exit'] == 0 and result.get('passed') is True
                         and result.get('gui_shutdown') is True and checks and all(checks.values())
                         and identity.get('packaged') is True
                         and Path(identity.get('executable_path', '')).resolve() == executable
                         and startup.get('passed') is True and startup.get('passive_cli_startup') is True)
        if args.part == 'edits':
            case_passed = (len(result.get('edits', [])) == 30 and len(result.get('saves', [])) == 4
                           and checks.get('saved content readback') is True
                           and result.get('manual_requests_during_E') == 0
                           and (output/'after-thirty.png').is_file())
        elif args.part == 'saves':
            case_passed = (len(result.get('saves', [])) == 4
                           and checks.get('saved content readback') is True)
        elif args.part == 'waveform':
            case_passed = (len(checks) >= 4 and result.get('serial_before') == result.get('serial_after')
                           and (output/'waveform-stable.png').is_file())
        else:
            case_passed = (len(result.get('views', [])) == 3 and len(result.get('interactions', [])) == 47
                           and checks.get('decoded coverage reaches recording end') is True
                           and (output/'whole-recording.png').is_file())
        summary['passed'] = bool(common_passed and case_passed)
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
        (output/'edit-save-summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2)+'\n', 'utf8')
    print(json.dumps(dict(passed=summary['passed'], checks=summary.get('checks'),
                          launcher_exit=summary.get('launcher_exit'), output=str(output))))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
