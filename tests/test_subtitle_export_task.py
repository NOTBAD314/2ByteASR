import os
import threading
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from twobyteasr.exports import studio_export_ui as ui
from twobyteasr.exports.studio_subtitle_export import export_language_layers, export_subtitle_artifacts
from twobyteasr.exports.subtitle_export_task import SubtitleExportTask
from twobyteasr.exports.subtitle_snapshot import SubtitleSnapshot
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import state_for, DirtyDomain

APP = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def local_fault_injection_backend(monkeypatch):
    from twobyteasr.exports.subtitle_export_task import SubtitleExportTask
    monkeypatch.setattr(SubtitleExportTask, '_run_process', SubtitleExportTask._run)


def project(tmp_path):
    result = SubtitleProject(StudioMedia(str(tmp_path / 'source.mp4'), duration_ms=4000),
        cues=[StudioCue('a', 0, 1000, '原文')])
    result.validate()
    return result


class RuntimeOwner:
    def __deepcopy__(self, memo):
        raise AssertionError('runtime owner was copied')


def wait_task(task):
    assert task.done.wait(10)


def wait_dialog(dialog):
    deadline = time.monotonic() + 10
    while dialog._subtitle_task is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert dialog._subtitle_task is None


def test_snapshot_excludes_runtime_on_project_and_cues_and_is_detached(tmp_path):
    p = project(tmp_path)
    p._runtime_owner = RuntimeOwner()
    p.cues[0]._runtime_owner = RuntimeOwner()
    state_for(p)._subscribers.append(RuntimeOwner())
    snapshot = SubtitleSnapshot.capture(p)
    p.cues[0].text = '新编辑'
    frozen = snapshot.materialize()
    assert frozen.cues[0].text == '原文'
    assert not hasattr(frozen, '_runtime_owner')
    assert not hasattr(frozen.cues[0], '_runtime_owner')
    frozen.studio_state['worker'] = True
    assert 'worker' not in p.studio_state


def test_snapshot_rejects_active_transaction_and_nondata_document_field(tmp_path):
    p = project(tmp_path)
    with state_for(p).transaction(p, action_id='test', dirty=DirtyDomain.CUE_CONTENT):
        with pytest.raises(RuntimeError, match='事务'):
            SubtitleSnapshot.capture(p)
    p.cues[0].appearance_override['bad'] = RuntimeOwner()
    with pytest.raises((ValueError, TypeError)):
        SubtitleSnapshot.capture(p)


def test_task_uses_one_snapshot_and_releases_it_after_success(tmp_path, monkeypatch):
    p = project(tmp_path)
    p.generation_metadata['translations'] = {'a': '译文'}
    task = SubtitleExportTask(SubtitleSnapshot.capture(p), tmp_path, 'out', {'srt', 'txt'},
        ('original', 'translation', 'bilingual'), 'combined', True,
        export_subtitle_artifacts, export_language_layers)
    monkeypatch.setattr(SubtitleSnapshot, 'capture', lambda *_: pytest.fail('second snapshot'))
    task.start()
    wait_task(task)
    assert task.error is None
    assert len(task.artifacts) == 4
    assert task.snapshot is None and task._arguments is None
    assert not list(tmp_path.glob('.subtitle-*'))


def test_cancel_before_write_preserves_existing_file_and_releases_snapshot(tmp_path):
    p = project(tmp_path)
    target = tmp_path / 'out.srt'
    target.write_text('existing', encoding='utf-8')
    task = SubtitleExportTask(SubtitleSnapshot.capture(p), tmp_path, 'out', {'srt'}, (),
        'combined', True, export_subtitle_artifacts, export_language_layers)
    task.cancel.set()
    task.start()
    wait_task(task)
    assert task.exception_type == 'SubtitleExportCancelled'
    assert target.read_text(encoding='utf-8') == 'existing'
    assert task.snapshot is None and not list(tmp_path.glob('.subtitle-*'))


def test_dialog_ignores_double_click_and_close_cancels_without_late_ui(tmp_path, monkeypatch):
    p = project(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    def delayed(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return export_subtitle_artifacts(*args)
    monkeypatch.setattr(ui, 'export_subtitle_artifacts', delayed)
    dialog = ui.SubtitleExportDialog(p, export_on_accept=True)
    dialog._run_export()
    task = dialog._subtitle_task
    assert entered.wait(5)
    dialog._run_export()
    assert calls == [1]
    dialog.reject()
    dialog.deleteLater()
    APP.processEvents()
    release.set()
    wait_task(task)
    assert task.exception_type == 'SubtitleExportCancelled'
    assert not list(tmp_path.glob('*.srt'))


def test_failed_dialog_can_retry_and_uses_latest_committed_edit(tmp_path, monkeypatch):
    p = project(tmp_path)
    real = ui.export_subtitle_artifacts
    def fail(*_args):
        raise OSError('磁盘已满')
    monkeypatch.setattr(ui, 'export_subtitle_artifacts', fail)
    dialog = ui.SubtitleExportDialog(p, export_on_accept=True)
    dialog._run_export()
    wait_dialog(dialog)
    assert dialog.export_button.isEnabled() and '磁盘已满' in dialog.warning.text()
    monkeypatch.setattr(ui, 'export_subtitle_artifacts', real)
    p.cues[0].text = '最新正文'
    dialog._run_export()
    wait_dialog(dialog)
    assert dialog.artifacts[0].path.read_text(encoding='utf-8').endswith('最新正文\n')
    dialog.close()
