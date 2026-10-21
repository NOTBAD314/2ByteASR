"""Normal-window, private-desktop replay of the supplied recognition artifacts.

This performs no ASR or cloud inference. Original files are only read; copies,
glossary changes, projects, captures and receipts stay in a fresh tmp directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, default=ROOT/'tmp/recognition-correctness-20261006/terms')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--live-result', type=Path,
        help='Existing real service receipt under repository tmp; delivered without recreating its project or reference')
    parser.add_argument('--allow-partial-home-delivery', action='store_true',
        help='Verify only saved delivery/export of an actual partial Home run; preserve its failed cloud status')
    parser.add_argument('--scale', default='1')
    args = parser.parse_args()
    output, inputs = args.output.resolve(), args.inputs.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh output under repository tmp')
    if not inputs.is_relative_to(ROOT/'tmp'):
        raise ValueError('Only retained audit copies under repository tmp are accepted')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    live = None
    live_hashes = {}
    if args.live_result:
        live_path = args.live_result.resolve()
        if not live_path.is_relative_to(ROOT/'tmp'):
            raise ValueError('The live service receipt must be a retained tmp artifact')
        source = json.loads(live_path.read_text('utf8'))
        partial_home = bool(args.allow_partial_home_delivery and source.get('inference_run')
            and source.get('gui_shutdown') and 'queue_result' in source)
        queue = source.get('queue_result') if partial_home else source.get('queue')
        if not isinstance(queue, dict) or len(queue.get('results', [])) != 1 or (not source.get('passed') and not partial_home):
            raise ValueError('A successful single-media live receipt is required')
        item = queue['results'][0]
        reference = json.loads(item['result_ref_json'])
        project_path, media_path = Path(item['project_path']).resolve(), Path(item['media_path']).resolve()
        if any(not path.is_relative_to(ROOT/'tmp') for path in (project_path, media_path)):
            raise ValueError('Live project and media must stay within retained tmp artifacts')
        if Path(reference['path']).resolve() != project_path or reference['job_id'] != queue['job_id']:
            raise ValueError('The live receipt must retain its exact committed result reference')
        live = dict(queue=queue, reference=reference, source_receipt=str(live_path),
            project=str(project_path), media=str(media_path), upstream_inference_run=True,
            upstream_passed=bool(source.get('passed')), partial_home_delivery_only=partial_home,
            upstream_outcome=source.get('actual_outcome'), upstream_error=source.get('error'))
        live_hashes = {str(path): sha(path) for path in (live_path, project_path, media_path)}
    original_files = {name: inputs/name for name in ('source-project.2byteproj',
        'source-polished.json', 'current-library-readonly.json', 'input-report.txt')}
    original_hashes = {name: sha(path) for name, path in original_files.items()}
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    os.environ['TWOBYTEASR_STARTUP_TRACE'] = str(output/'startup.jsonl')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project, save_project
    retained = load_project(original_files['source-project.2byteproj'])
    media_source = Path(retained.media.path)
    media_before = sha(media_source)
    media = output/'media'/media_source.name
    media.parent.mkdir()
    shutil.copy2(media_source, media)
    for name, source in original_files.items():
        shutil.copy2(source, output/name)
    store = output/'local/2ByteASR/learned_game_terms.json'
    store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output/'current-library-readonly.json', store)
    old_media_path = retained.media.path
    retained.media.path = str(media)
    for asset in retained.media_pool:
        if asset.canonical_source == old_media_path:
            asset.canonical_source = str(media)
    fixture = output/'projects/retained/retained.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(retained, fixture)
    manifest = dict(scope='Retained real 48-cue project / 50 processing records, offline normal UI replay; no new inference',
        source_sha256=original_hashes, media_sha256=media_before, media=str(media),
        fixture=str(fixture), requested_scale=args.scale)
    if live:
        live_copy = output/'live-delivery.json'
        live_copy.write_text(json.dumps(live, ensure_ascii=False, indent=2), 'utf8')
        manifest.update(live_result=str(live_copy), live_source_sha256=live_hashes,
            scope=manifest['scope']+'; exact saved delivery/export only; upstream cloud quality and failures remain in live-delivery.json')
    (output/'input.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf8')
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='recognition-correctness',
        TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale, PYTHONUTF8='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if live:
        env['TWOBYTEASR_ACCEPTANCE_LIVE_RESULT'] = str(output/'live-delivery.json')
    else:
        env.pop('TWOBYTEASR_ACCEPTANCE_LIVE_RESULT', None)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=240)
    receipt = output/'result.json'
    result, deadline = {}, time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            result = json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    result['launcher_exit'] = code
    result['original_copies_unchanged'] = all(sha(path) == original_hashes[name]
        for name, path in original_files.items())
    result['original_media_unchanged'] = sha(media_source) == media_before == sha(media)
    if live:
        after = {path: sha(path) for path in live_hashes}
        result['live_source_hashes_before'] = live_hashes
        result['live_source_hashes_after'] = after
        result['live_sources_unchanged'] = after == live_hashes
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0
        and result['original_copies_unchanged'] and result['original_media_unchanged']
        and result.get('live_sources_unchanged', True))
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])),
        error=result.get('error'), launcher_exit=code, output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
