"""Probe the unchanged, SHA-verified candidate through private worker pipes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import pickle
import signal
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--receipts', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
out = args.output.resolve()
assert not out.exists() and 'tmp' in out.parts
out.mkdir(parents=True)
app = Path('/Applications/2ByteASR.app')
assert not app.exists()
dmg = next(args.inputs.rglob('*.dmg'))
receipt = json.loads((args.receipts / 'dmg/dmg-result.json').read_text('utf8'))
h = hashlib.sha256()
with dmg.open('rb') as stream:
    for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
        h.update(chunk)
assert receipt['passed'] and h.hexdigest() == receipt['artifact']['sha256'] == '9bdb60fee242a30eb6162a5269b31a7fca38ae2098dbb8c62027c44f8c47892e'
mount = out / 'mounted'
mount.mkdir()
subprocess.run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg)], check=True)
subprocess.run(['/usr/bin/ditto', str(mount / '2ByteASR.app'), str(app)], check=True)
subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)], check=True)
subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
from twobyteasr.test_isolation import install
install()
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.exports.subtitle_snapshot import SubtitleSnapshot
from scripts.verify_blank_project_macos import blank_environment
simple = SubtitleProject(StudioMedia(''), cues=[StudioCue('one', 0, 1000, '私有管道字幕')])
retained = load_project(args.receipts / 'desktop-flow/owned-projects/final.2byteproj')
cases = []
for name, project, formats in [('simple-srt', simple, {'srt'}), ('retained-srt', retained, {'srt'}),
                              ('retained-four', retained, {'srt', 'ass', 'txt', 'json'})]:
    case = out / name
    case.mkdir()
    target = save_project(SubtitleProject(StudioMedia('')), case / 'startup.2byteproj')
    env = blank_environment(case, out, target)
    env.pop('TWOBYTEASR_ACCEPTANCE_SCENARIO', None)
    snapshot = SubtitleSnapshot.capture(project)
    request = dict(snapshot=snapshot, parameters=(case / 'exports', 'probe', formats, (), 'combined', False),
        task_id=uuid.uuid4().hex, cancel_path=str(case / 'cancel'))
    data = pickle.dumps(request, protocol=5)
    process = subprocess.Popen([str(app / 'Contents/MacOS/2ByteASR'), '--subtitle-export-worker'],
        cwd=out, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)
    row = dict(name=name, pid=process.pid, input_bytes=len(data), snapshot_bytes=len(snapshot.data), passed=False)
    started = time.monotonic()
    try:
        stdout, stderr = process.communicate(data, timeout=30)
        row.update(exit=process.returncode, stdout_bytes=len(stdout), stderr=stderr.decode('utf8', 'replace')[-5000:])
        (case / 'stdout.bin').write_bytes(stdout)
        if process.returncode == 0:
            reply = pickle.loads(stdout)  # only the verified app's owned private pipe
            row.update(reply_error=reply['error'], reply_details=reply['details'], artifacts=[str(a.path) for a in reply['artifacts']])
            row['passed'] = not reply['error'] and len(reply['artifacts']) == len(formats)
    except subprocess.TimeoutExpired:
        row.update(timeout=True, exit_at_timeout=process.poll())
        for command, file in [(['/usr/bin/sample', str(process.pid), '3', '-file', str(case / 'sample.txt')], 'sample-command.log'),
                              (['/usr/sbin/lsof', '-p', str(process.pid)], 'lsof.txt'),
                              (['/bin/ps', '-axo', 'pid,ppid,state,command'], 'processes.txt')]:
            with (case / file).open('wb') as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=15)
    except Exception:
        row['error'] = traceback.format_exc()
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        row['seconds'] = round(time.monotonic() - started, 3)
        cases.append(row)
        (out / 'result.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), 'utf8')
        print(json.dumps(row, ensure_ascii=False), flush=True)
