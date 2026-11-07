"""Inspect native source-entry layout inside an isolated disposable profile."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import runpy
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def install_observer():
    from twobyteasr.acceptance import macos_edit_save_entry

    def start(window, output):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QWidget, QSplitter
        started = time.monotonic()
        timer = QTimer(window)
        timer.setInterval(500)
        samples, actions = [], set()

        def geometry(widget):
            row = dict(type=type(widget).__name__, name=widget.objectName(),
                       rect=list(widget.geometry().getRect()), hidden=widget.isHidden(),
                       visible=widget.isVisible(), minimum=list(widget.minimumSize().toTuple()),
                       hint=list(widget.minimumSizeHint().toTuple()))
            if isinstance(widget, QSplitter):
                row['sizes'] = widget.sizes()
                row['children'] = [type(widget.widget(i)).__name__ for i in range(widget.count())]
            return row

        def observe():
            page = window.built_page('studio')
            elapsed = time.monotonic()-started
            if page is None:
                return
            gate, chain, widget = page._readiness, [], page.video
            while isinstance(widget, QWidget):
                chain.append(geometry(widget))
                widget = widget.parentWidget()
            samples.append(dict(elapsed=elapsed, ready=gate.ready, active=gate.active,
                hydrated=gate.hydrated, completed=sorted(gate.completed), chain=chain,
                parts={name: geometry(getattr(page, name)) for name in (
                    'workspace_host', 'workspace_splitter', 'upper_splitter', 'center_splitter',
                    'video_overlay_host', 'position_overlay', 'source_tabs', 'context_panel')}))
            (output/'geometry.json').write_text(json.dumps(samples, indent=2), 'utf8')
            if elapsed > 14 and 'settle' not in actions and not gate.ready:
                actions.add('settle')
                window._prepare_hidden_studio_geometry(page, force_settle=True)
            if elapsed > 20 and 'wide' not in actions and not gate.ready:
                actions.add('wide')
                window.resize(1600, 1000)
                window._prepare_hidden_studio_geometry(page, force_settle=True)
            if gate.ready or not gate.active or elapsed > 40:
                timer.stop()
                window.grab().save(str(output/'window.png'))
                (output/'source-entry.json').write_text(json.dumps(dict(
                    ready=gate.ready, elapsed=elapsed, actions=sorted(actions),
                    native_backend=page.video.controller.backend,
                    release_acceptance=False), indent=2), 'utf8')
                window.close()
        timer.timeout.connect(observe)
        timer.start()
    macos_edit_save_entry.start = start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dmg', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', type=Path)
    args = parser.parse_args()
    if args.child:
        install_observer()
        sys.argv = ['2ByteASR', str(args.child)]
        runpy.run_module('twobyteasr', run_name='__main__')
        return
    assert sys.platform == 'darwin' and platform.machine() == 'arm64'
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    receipt = json.loads(args.receipt.read_text('utf8'))
    assert receipt['source_identity']['git_sha'] == 'f6891cab516d690b67e9f385355fb5fb2a1b56ca'
    digest = hashlib.sha256()
    with args.dmg.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    assert digest.hexdigest() == receipt['artifact']['sha256']
    from scripts.verify_blank_project_macos import audit_boundary, blank_environment
    from scripts.macos_edit_save_smoke import prepare_fixture
    output, invoker = audit_boundary(args.output)
    output.mkdir(parents=True)
    mount = output/'mounted'
    mount.mkdir()
    app = Path('/Applications/2ByteASR.app')
    assert not app.exists()
    subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen',
                    '-mountpoint', str(mount), str(args.dmg)], check=True)
    try:
        subprocess.run(['ditto', str(mount/app.name), str(app)], check=True)
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
    tool_bin = app/'Contents/Frameworks/tools/ffmpeg/bin'
    assert (tool_bin/'ffmpeg').is_file()
    case = output/'case'
    case.mkdir()
    target = prepare_fixture(case, tool_bin/'ffmpeg')
    env = blank_environment(case, invoker, target)
    env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='macos-edit-save', EDIT_SAVE_PROJECT=str(target),
               EDIT_SAVE_PART='edits', PYTHONPATH=str(ROOT), PATH=str(tool_bin)+':'+env['PATH'])
    with (case/'application.log').open('wb') as stream:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', str(target)],
            cwd=invoker, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            code = process.wait(timeout=20)
    receipts = output/'receipts'
    receipts.mkdir()
    for name in ('geometry.json', 'source-entry.json', 'window.png', 'application.log'):
        path = case/name
        if path.exists():
            shutil.copyfile(path, receipts/name)
    (receipts/'process.json').write_text(json.dumps(dict(exit_code=code, release_acceptance=False)), 'utf8')


if __name__ == '__main__':
    main()
