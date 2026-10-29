"""Run one normal private-desktop export audit on a copied real project."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def relocate_media(value, original, replacement):
    """Only replace references to the exact primary source, including AV DTOs."""
    if isinstance(value, dict):
        return {key: relocate_media(item, original, replacement) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate_media(item, original, replacement) for item in value]
    if isinstance(value, str) and value.replace('\\', '/').casefold() == original.replace('\\', '/').casefold():
        return replacement
    return value


def relocate_project_media(payload, original, replacement):
    """Validate the original autosave before rebinding its owned copy's source."""
    from twobyteasr.projects.media_graph_integrity import graph_integrity, validate_autosave_integrity
    original_integrity = validate_autosave_integrity(payload)
    result = relocate_media(payload, original, replacement)
    relocated_integrity = graph_integrity(result)
    if original_integrity is not None:
        # The graph paths deliberately refer to a frozen byte-identical source.
        # Keep the snapshot envelope valid only for this derived tmp fixture.
        result['autosave']['media_graph_integrity'] = relocated_integrity
    return result, dict(original_source=original, relocated_source=replacement,
        original_graph_integrity=original_integrity,
        relocated_graph_integrity=relocated_integrity,
        scope='validate original envelope, then rebind owned tmp graph paths; original unchanged')


def project_timeline_extent(payload):
    """Read saved sequence/AV bounds using the production timeline extent rule."""
    sequence = payload.get('edit_sequence') or {}
    segments = sequence.get('segments') or []
    sequence_end = max((int(row['timeline_out_ms']) for row in segments), default=
        0 if sequence.get('empty_timeline') else int(sequence.get('source_duration_ms') or payload['media']['duration_ms']))
    linked_audio = {row['audio_track_id'] for row in payload.get('av_track_groups', []) if row.get('linked', True)}
    video_end = max((int(clip['timeline_out_ms']) for row in payload.get('video_tracks', [])
        for clip in row.get('clips', [])), default=0)
    audio_end = max((int(clip['timeline_out_ms']) for row in payload.get('audio_tracks', [])
        if row['id'] not in linked_audio for clip in row.get('clips', [])), default=0)
    caption_end = max((int(row['end_ms']) for row in payload.get('cues', [])), default=0
        ) if payload.get('render_settings', {}).get('_cue_domain') == 'timeline' else 0
    # studio_edit_sequence.timeline_duration_ms: sequence, editable AV graph
    # (linked audio excluded), and already independent timeline captions.
    extent = max(sequence_end, video_end, audio_end, caption_end, 0)
    if extent <= 0:
        raise ValueError('A nonempty actual project timeline is required')
    return dict(timeline_ms=extent, sequence_end_ms=sequence_end, video_end_ms=video_end,
        unlinked_audio_end_ms=audio_end, independent_caption_end_ms=caption_end,
        source_container_ms=int(payload['media']['duration_ms']),
        rule='studio_edit_sequence.timeline_duration_ms / studio_media_pool.media_graph_duration_ms')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--project', required=True, type=Path, help='Real autosave or its frozen before copy')
    parser.add_argument('--source', type=Path, help='Read-only source, optionally the frozen before copy')
    parser.add_argument('--copy-source', action='store_true')
    parser.add_argument('--old-output', type=Path, help='Hash protection only; never overwritten')
    parser.add_argument('--scope', choices=('controls', 'short', 'full', 'queue', 'edges'), default='controls')
    parser.add_argument('--encoder-plan', choices=('mixed', 'software', 'auto'), default='mixed')
    parser.add_argument('--variant', choices=('authored', 'native', 'alpha'), default='authored')
    parser.add_argument('--audio', choices=('aac', 'copy', 'none'), default='aac')
    parser.add_argument('--start', type=float, default=20.)
    parser.add_argument('--seconds', type=float, default=20.)
    parser.add_argument('--expected-fps', type=float, default=60.)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--job-timeout', type=int, default=600)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scale', choices=('1', '1.25', '1.5'), default='1')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to((ROOT/'tmp').resolve()):
        parser.error('Use a fresh output directory within repository tmp')
    if not args.project.is_file():
        parser.error('The real project/autosave is required')
    payload = json.loads(args.project.read_text(encoding='utf-8-sig'))
    source = (args.source or Path(payload['media']['path'])).resolve()
    if not source.is_file():
        parser.error('The read-only source must be accessible')
    extent = project_timeline_extent(payload)
    full_seconds = extent['timeline_ms']/1000
    if args.seconds <= 0 or args.start < 0 or args.start+args.seconds > full_seconds:
        parser.error('Representative range must fit inside the real source')
    if args.scope == 'full' and args.variant != 'authored':
        parser.error('The full original-engine check must retain the authored user design')
    originals = {str(args.project.resolve()): file_hash(args.project), str(source): file_hash(source)}
    if args.old_output:
        if not args.old_output.is_file():
            parser.error('The protected old product must exist')
        originals[str(args.old_output.resolve())] = file_hash(args.old_output)
    output.mkdir(parents=True)
    fixture = output/'inputs'
    fixture.mkdir()
    original_copy = fixture/'original-autosave.2byteproj'
    shutil.copy2(args.project, original_copy)
    if args.copy_source:
        copied_source = fixture/source.name
        shutil.copy2(source, copied_source)
        source = copied_source
    # Set isolation and the explicit trace before importing the application.
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    os.environ['TWOBYTEASR_STARTUP_TRACE'] = str(output/'startup-trace.jsonl')
    old_path = payload['media']['path']
    payload, relocation = relocate_project_media(payload, old_path, str(source))
    from twobyteasr.acceptance.export_target_audit import content_hash, prepare_variant
    variant = prepare_variant(payload, args.variant)
    project_path = fixture/'audit.2byteproj'
    project_path.write_text(json.dumps(variant, ensure_ascii=False, indent=2), encoding='utf-8')
    inputs = dict(project=str(project_path), source=str(source), original_project=str(original_copy),
        original_files=originals, scope=args.scope, variant=args.variant, audio=args.audio,
        encoder_plan=args.encoder_plan,
        start_seconds=args.start, short_seconds=args.seconds, full_seconds=full_seconds,
        source_container_seconds=extent['source_container_ms']/1000, timeline_extent=extent,
        expected_fps=args.expected_fps, width=payload['media']['width'], height=payload['media']['height'],
        job_timeout=args.job_timeout, requested_scale=args.scale,
        authored_project_hash=content_hash(payload), fixture_project_hash=content_hash(variant),
        source_relocation=relocation,
        manual_caption_count=len(variant.get('studio_state', {}).get('manual_caption_text', {})),
        variant_scope='unchanged authored design' if args.variant == 'authored' else 'explicitly derived renderer fixture; text/time/speaker/ASR retained')
    (output/'input.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')
    from twobyteasr.test_isolation import install
    install()
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO', 'TWOBYTEASR_READINESS_VISUAL'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='export-target-real',
        TWOBYTEASR_STARTUP_PROJECT=str(project_path), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),
        TWOBYTEASR_EXPORT_LOG_ROOT=str(output/'diagnostics'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0',
        QT_FONT_DPI='96', QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough', PYTHONUTF8='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=args.timeout)
    target = output/'result.json'
    result = json.loads(target.read_text(encoding='utf-8')) if target.is_file() else dict(passed=False, error='No normal GUI receipt')
    result.update(process_exit=code, normal_entry_command=command)
    result['original_file_hashes_unchanged'] = all(Path(path).is_file() and file_hash(path) == digest
        for path, digest in originals.items())
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0
        and result['original_file_hashes_unchanged'] and result.get('provider_calls') == 0)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'], output=str(output), scope=args.scope,
        checks=len(result.get('checks', [])), exports=len(result.get('exports', [])),
        process_exit=code, error=result.get('error')), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
