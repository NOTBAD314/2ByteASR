"""Fixed-data cold/warm persistence phases, including local process round trips."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        parser.error('fresh source/tmp output required')
    out.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out / 'profile'), QT_QPA_PLATFORM='offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.projects import studio_save as saves
    from twobyteasr.diagnostics.save_trace import SaveTrace, phase
    from twobyteasr.system.resident_worker import close_shared_worker
    app = QApplication([])
    original_hash = hashlib.sha256(args.project.read_bytes()).hexdigest()
    started = time.perf_counter()
    project = load_project(args.project)
    page = QWidget()
    page._revision_store = StudioRevisionStore(project)
    page._autosave_timer = QTimer(page)
    page._autosave_write_lock = threading.Lock()
    opened_ms = (time.perf_counter()-started)*1000
    target = args.target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.project, target)
    results = []
    original_writer = saves.save_project_revision
    phases = {}
    def writer(revision, path):
        saved, values = original_writer(revision, path, compact=args.compact)
        phases.clear()
        phases.update(values)
        return saved, values
    saves.save_project_revision = writer
    for index, name in enumerate(('cold-two-edits', 'unchanged', 'two-edits', 'batch-thirty')):
        if name != 'unchanged':
            for cue in project.cues[:30 if name == 'batch-thirty' else 2]:
                cue.text += f' 验收{index}'
        trace = SaveTrace()
        times = []
        previous = [time.perf_counter()]
        def heartbeat():
            now = time.perf_counter()
            times.append((now-previous[0])*1000)
            previous[0] = now
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(heartbeat)
        timer.start()
        start = time.perf_counter()
        with trace.activate(), trace.observe_gc():
            with phase('gui.snapshot'):
                revision = saves.capture_manual_save(page, project, index)
            snapshot_ms = (time.perf_counter()-start)*1000
            saves.persist_with_progress(page, revision, target)
        times.append((time.perf_counter()-previous[0])*1000)
        timer.stop()
        row = dict(case=name, snapshot_ms=snapshot_ms, total_ms=(time.perf_counter()-start)*1000,
            max_gui_gap_ms=max(times), input_bytes=args.project.stat().st_size,
            output_bytes=target.stat().st_size, phases=dict(phases), trace=trace.payload())
        results.append(row)
        print(json.dumps({k:row[k] for k in ('case','snapshot_ms','total_ms','max_gui_gap_ms','output_bytes')}) , flush=True)
        reopened = load_project(target)
        if [c.text for c in reopened.cues] != [c.text for c in project.cues]:
            raise AssertionError('saved cue text mismatch')
    close_shared_worker()
    (out/'result.json').write_text(json.dumps(dict(open_ms=opened_ms, results=results,
        original_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==original_hash),ensure_ascii=False,indent=2),'utf8')


if __name__ == '__main__':
    main()
