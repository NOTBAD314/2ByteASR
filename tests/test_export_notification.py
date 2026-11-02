"""Exercise completion notifications on the real workspace interface."""
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.exports.studio_render import RenderJob,RenderSettings
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia

APP=QApplication.instance() or QApplication([])

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(StudioExportWorkspace,'_populate_encoders',lambda self:None)
    project=SubtitleProject(media=StudioMedia(str(tmp_path/'source.mp4'),duration_ms=40000))
    window=StudioExportWorkspace(project,'');window.show();APP.processEvents()
    yield window
    window.release_preview();window.deleteLater();APP.processEvents()


def test_completed_receipt_notifies_once_and_os_failure_does_not_hide_success(workspace,monkeypatch,tmp_path):
    notifications=[]
    def notify(parent,path):
        notifications.append(path)
        raise OSError('notification service unavailable')
    monkeypatch.setattr('twobyteasr.exports.export_notification.notify_export_completed',notify)
    output=tmp_path/'成片.mp4';output.write_bytes(b'publication UI fixture')
    job=RenderJob('source.mp4','',str(output),RenderSettings())
    job.completion_metadata.update(output_path=str(output),published_monotonic=1,elapsed_seconds=1)
    workspace._last_job=job
    workspace._show_success(str(output));APP.processEvents();workspace._show_success(str(output));APP.processEvents()
    assert notifications==[output]
    assert not workspace._running and workspace.pages.currentWidget() is workspace.success_page
    workspace._completion_notified=False
    workspace._show_success(str(output))
    from PySide6.QtTest import QTest
    QTest.qWait(550)  # Same visible page uses the reviewed after-paint fallback.
    assert notifications==[output,output]


def test_preview_warning_is_visible_on_success_without_changing_receipt(workspace,monkeypatch,tmp_path):
    monkeypatch.setattr('twobyteasr.exports.export_notification.notify_export_completed',lambda *a:None)
    output=tmp_path/'completed.mp4';output.write_bytes(b'publication UI fixture')
    job=RenderJob('source.mp4','',str(output),RenderSettings())
    job.export_context.update(preview_warning={'reason':'decoder observer failed'},diagnostics_path=str(tmp_path/'logs'))
    workspace._last_job=job
    workspace._show_success(str(output))
    assert workspace.pages.currentWidget() is workspace.success_page
    assert not workspace.success_page.error.isHidden()
    assert '成片已完整校验' in workspace.success_page.error.text()
    assert str(tmp_path/'logs') in workspace.success_page.error.text()
    assert output.read_bytes()==b'publication UI fixture'
