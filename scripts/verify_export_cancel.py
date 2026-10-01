"""Verify HTML cancellation using ordinary Studio/export/cancel buttons.

Example (append --exe dist/2ByteASR/2ByteASR.exe for the complete frozen build):
  .venv-main/Scripts/python.exe scripts/verify_export_cancel.py --output tmp/cancel-source --project tmp/preset-export-20260911/html.2byteproj --old-output tmp/name-playhead-receipt-20260912/source-native/verified.mp4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--old-output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--cancel-limit-ms', type=float, default=1500)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((root/'tmp').resolve()) or output.exists():
        raise ValueError('Use a fresh repository tmp directory; previous evidence is retained')
    output.mkdir(parents=True)
    env = os.environ.copy()
    env.update(LOCALAPPDATA=str(output/'local'), APPDATA=str(output/'roaming'),
        TEMP=str(output/'temp'), TMP=str(output/'temp'), QT_QPA_PLATFORM='windows',
        PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
        TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-runtime',
        TWOBYTEASR_CAPTION_AUDIT_MODE='preset-export', TWOBYTEASR_EXPORT_CANCEL_AUDIT='1',
        TWOBYTEASR_STARTUP_PROJECT=str(output/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(output/'startup.jsonl'))
    for key in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
        os.environ[key] = env[key]
    # Load only after isolating the launcher too; the application additionally
    # isolates QSettings/project roots and disables probes via caption-runtime.
    from twobyteasr.studio_project import load_project, save_project
    from twobyteasr.studio_edit_sequence import sequence_of
    project_path = args.project.resolve()
    old_path = args.old_output.resolve()
    originals = {str(project_path): sha256(project_path), str(old_path): sha256(old_path)}
    project = load_project(project_path)
    sequence = sequence_of(project)
    sources = {project.media.path, *(asset.canonical_source for asset in project.media_pool),
               sequence.source_path, *(segment.source_path for segment in sequence.segments)}
    mapped = {}
    media_dir = output/'media'
    media_dir.mkdir()
    for index, source in enumerate(sorted(path for path in sources if path)):
        path = Path(source).resolve()
        if not path.is_file(): raise FileNotFoundError(path)
        destination = media_dir/(str(index)+path.suffix)
        originals[str(path)] = sha256(path)
        shutil.copyfile(path, destination)
        mapped[source] = str(destination)
    project.media.path = mapped[project.media.path]
    for asset in project.media_pool:
        asset.canonical_source = mapped[asset.canonical_source]
    sequence.source_path = mapped.get(sequence.source_path, project.media.path)
    for segment in sequence.segments:
        segment.source_path = mapped.get(segment.source_path, sequence.source_path)
    if sequence.danmaku_path:
        path = Path(sequence.danmaku_path).resolve()
        if path.is_file():
            originals[str(path)] = sha256(path)
            shutil.copyfile(path, media_dir/'copied-danmaku.xml')
            sequence.danmaku_path = str(media_dir/'copied-danmaku.xml')
        else:
            sequence.danmaku_path = ''
    project.report_path = ''
    project.original_outputs = {}
    save_project(project, output/'fixture.2byteproj')
    shutil.copyfile(old_path, output/'old-output-copy.mp4')
    (output/'cancel-config.json').write_text(json.dumps(dict(timeout_seconds=args.timeout,
        cancel_limit_ms=args.cancel_limit_ms, source_hashes=originals), indent=2), encoding='utf8')
    from twobyteasr.processes import run_hidden_subprocess
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(root/'quick_start.py')]
    with (output/'process.log').open('w', encoding='utf8') as log:
        child = run_hidden_subprocess(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
            timeout=args.timeout+45, purpose='Isolated normal HTML export cancellation audit')
    result_path = output/'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else dict(passed=False, error='Audit did not produce result.json')
    result['source_files_unchanged'] = all(Path(path).is_file() and sha256(path) == digest for path, digest in originals.items())
    result['process_exit_code'] = child.returncode
    import psutil
    alive = []
    for row in result.get('application_children', []):
        try:
            process = psutil.Process(row['pid'])
            if process.create_time() == row['created'] and process.is_running(): alive.append(row)
        except psutil.Error:
            pass
    result['application_children_after_exit'] = alive
    result['passed'] = bool(result.get('passed') and result['source_files_unchanged'] and child.returncode == 0 and not alive)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({key: result.get(key) for key in ('passed', 'cancel_return_ms', 'source_files_unchanged', 'checks', 'error')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
