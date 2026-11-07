"""Collect entry-readiness diagnostics from an unchanged candidate DMG."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.macos_edit_save_smoke import prepare_fixture
from scripts.verify_blank_project_macos import audit_boundary, blank_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dmg', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'darwin' and platform.machine() == 'arm64' and os.environ.get('GITHUB_ACTIONS') == 'true'
    out, invoker = audit_boundary(args.output)
    expected = json.loads(args.receipt.read_text('utf8'))
    assert expected['passed'] and expected['source_identity']['git_sha'] == 'bcd71e4842b910af218e49b22187bb16664a71f9'
    digest = hashlib.sha256()
    with args.dmg.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    assert args.dmg.stat().st_size == expected['artifact']['bytes']
    assert digest.hexdigest() == expected['artifact']['sha256']
    app = Path('/Applications/2ByteASR.app')
    assert not app.exists()
    out.mkdir(parents=True)
    receipts = out/'receipts'
    receipts.mkdir()
    mount = out/'mounted'
    mount.mkdir()
    subprocess.run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen',
                    '-mountpoint', str(mount), str(args.dmg)], check=True, timeout=120)
    try:
        subprocess.run(['/usr/bin/ditto', str(mount/'2ByteASR.app'), str(app)], check=True, timeout=180)
    finally:
        subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)], check=True, timeout=60)
    executable = app/'Contents/MacOS/2ByteASR'
    ffmpeg = app/'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    if not ffmpeg.exists():
        ffmpeg = app/'Contents/Resources/tools/ffmpeg/bin/ffmpeg'
    rows = []
    for name, scenario in [('passive-cli', 'playback-stability'), ('edits-with-cli', 'edit-save')]:
        case = out/name
        case.mkdir()
        entry, target = prepare_fixture(case, ffmpeg)
        env = blank_environment(case, invoker, target)
        env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO=scenario, EDIT_SAVE_PROJECT=str(target),
                   EDIT_SAVE_PART='edits', STABILITY_AUDIO_ONLY='1')
        log = case/'application.log'
        with log.open('wb') as stream:
            process = subprocess.Popen([str(executable), str(target)], cwd=invoker, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=240)
            except subprocess.TimeoutExpired:
                code = 124
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=20)
        result = case/'result.json'
        row = dict(case=name, process_exit=code, scenario=scenario, cli_project=str(target))
        if result.is_file():
            row['application_result'] = json.loads(result.read_text('utf8'))
            shutil.copyfile(result, receipts/(name+'-result.json'))
        rows.append(row)
        for path in [log, *(case/'local/2ByteASR/logs').glob('*.log')]:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size-1024*1024))
                (receipts/(name+'-'+path.name)).write_bytes(stream.read())
        (receipts/'diagnostic-summary.json').write_text(json.dumps(dict(
            diagnostic_collection_complete=len(rows)==2, release_acceptance=False,
            source_sha=expected['source_identity']['git_sha'], dmg_sha256=digest.hexdigest(), cases=rows),
            ensure_ascii=False, indent=2), 'utf8')
    assert sum(path.stat().st_size for path in receipts.iterdir()) < 16*1024*1024


if __name__ == '__main__':
    main()
