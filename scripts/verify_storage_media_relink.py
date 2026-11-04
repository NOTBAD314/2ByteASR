"""Prepare a tiny sole-media fixture, optionally run normal Home acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.output.absolute(); fixture = args.fixture.absolute()
    from twobyteasr.storage.storage_service import safe_path
    if output.exists() or not safe_path(output, (ROOT / 'tmp',)):
        raise ValueError('Fresh owned tmp output required')
    if not safe_path(fixture, (ROOT / 'tmp',)) or fixture.stat().st_nlink != 1 or not 0 < fixture.stat().st_size <= 1024 * 1024:
        raise ValueError('Existing owned short fixture, under 1 MiB, required; no new media generated')
    fixture_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_STARTUP_TRACE=str(output / 'startup-trace.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.runtime_paths import get_runtime_paths
    from twobyteasr.storage.storage_service import StorageService
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project
    paths = get_runtime_paths()
    cache = paths.cache_root / 'media' / 'sole-proxy.mp4'; cache.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture, cache)
    missing = output / 'missing-original.mp4'
    service = StorageService(paths)
    assert service.register(cache, 'media', producer='headed_media_preservation_fixture', source=str(missing))
    project = SubtitleProject(media=StudioMedia(str(missing), duration_ms=2000, width=160, height=90),
        cues=[StudioCue('cue1', 350, 1100, '独立素材保存与重新定位')])
    project.validate()
    asset = project.media_pool[0]; asset.offline = True; asset.relink_state = 'offline'
    asset.audio_metadata['has_audio'] = False
    project.audio_tracks = []; project.av_track_groups = []
    clip = project.video_tracks[0].clips[0]
    clip.source_in_ms=200; clip.source_out_ms=1800; clip.timeline_in_ms=350; clip.timeline_out_ms=1150; clip.playback_rate=2.0
    # Construct the real persisted edited segment, preserving its stable clip id.
    from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment
    project.edit_sequence = EditSequence(source_path=str(missing), source_duration_ms=2000,
        segments=[VideoSegment(clip.id, str(missing), 200, 1800, 350, 1150)]).to_dict()
    path = paths.project_root / 'sole-edited' / 'sole-edited.2byteproj'; save_project(project, path)
    destination = path.parent / 'assets' / 'preserved-proxy.mp4'; destination.parent.mkdir()
    plan = dict(project=str(path), project_id=project.project_id, asset_id=asset.asset_id, cache=str(cache),
        source=str(missing), destination=str(destination), fixture=str(fixture), fixture_sha256=fixture_sha,
        logical_bytes=cache.stat().st_size, before=project.to_dict(), scope='Owned small complete media only; normal Home, Settings save, Studio relink/save and manual cleanup')
    (output / 'media-relink-input.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), 'utf8')
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, output=str(output), logical_bytes=plan['logical_bytes']), ensure_ascii=False)); return 0
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='storage-media-relink',
        TWOBYTEASR_STARTUP_PROJECT=str(path), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO','QT_SCALE_FACTOR','QT_FONT_DPI','QT_ENABLE_HIGHDPI_SCALING','QT_SCALE_FACTOR_ROUNDING_POLICY'):
        env.pop(key, None)
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.absolute())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    process_error = None
    try:
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=240)
    except Exception:
        code = None
        process_error = traceback.format_exc()
    receipt = output / 'media-relink-result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else dict(passed=False, error='No normal GUI receipt')
    if process_error:
        result.update(passed=False, process_error=process_error)
        result.setdefault('error',process_error)
    progress = output / 'media-relink-progress.json'
    if progress.is_file():result['last_progress']=json.loads(progress.read_text('utf8'))
    result['thread_stacks']='media-relink-thread-stacks.log'
    result.update(process_exit=code, fixture_unchanged=hashlib.sha256(fixture.read_bytes()).hexdigest() == fixture_sha)
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0 and result.get('provider_calls') == 0 and result['fixture_unchanged'])
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), error=result.get('error'), output=str(output)), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
