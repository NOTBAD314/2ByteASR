"""Video export owns its ASS; a disposable preview cannot gate the entry."""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.studio import studio_ui

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def page(tmp_path, monkeypatch):
    from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
    monkeypatch.setattr(StudioExportWorkspace, '_populate_encoders', lambda self: None)
    p = SubtitleStudioPage()
    p.project = SubtitleProject(media=StudioMedia(path=str(tmp_path/'media.mp4'), duration_ms=2000),
        cues=[StudioCue('c1', 100, 1800, '旧工程原文')])
    p.project.validate()
    p._preview_timer.stop()
    p._initial_preview_timer.stop()
    yield p
    if p.export_workspace is not None:
        p._close_export_workspace()
    p.close()
    p.deleteLater()
    APP.processEvents()


@pytest.mark.parametrize('preview', [None, 'deleted.ass'])
def test_export_entry_and_frozen_ass_do_not_require_preview(page, tmp_path, preview):
    page._preview_path = tmp_path/preview if preview else None
    page.studio_render_button.click()
    workspace = page.export_workspace
    assert workspace is not None
    job = workspace._job(tmp_path/'result.mp4')
    assert Path(job.ass_path).is_file()
    assert '旧工程原文' in Path(job.ass_path).read_text('utf8')
    assert job.ass_path != str(page._preview_path)
    page._close_export_workspace()
    assert page.studio_render_button.isEnabled()
    page.studio_render_button.click()
    assert page.export_workspace is not None


def test_failed_workspace_construction_explains_and_restores_retry(page, monkeypatch):
    messages = []
    original = studio_ui.StudioExportWorkspace
    def fail(*args, **kwargs):
        raise RuntimeError('controlled workspace setup failure')
    monkeypatch.setattr(studio_ui, 'StudioExportWorkspace', fail)
    monkeypatch.setattr(studio_ui, 'studio_message_box', lambda *a, **kw: messages.append((a, kw)))
    page._preview_path = Path('unused.ass')
    page.studio_render_button.click()
    dialog = page._export_issues_dialog
    assert dialog.isVisible() and 'controlled workspace setup failure' in dialog.detail.toPlainText()
    dialog.refresh()
    assert dialog.issues  # A task failure cannot be cleared by subtitle-only rechecking.
    dialog.close()
    assert page.export_workspace is None
    assert page.video_compositor._interaction_enabled
    assert page._export_return_ui is None
    assert page.studio_render_button.isEnabled()
    monkeypatch.setattr(studio_ui, 'StudioExportWorkspace', original)
    page.studio_render_button.click()
    assert page.export_workspace is not None


def test_subtitle_dialog_setup_error_has_user_message(page, monkeypatch):
    from twobyteasr.studio import studio_ass_flow
    messages=[]
    def fail(*args, **kwargs):
        raise RuntimeError('controlled subtitle setup failure')
    monkeypatch.setattr(studio_ass_flow,'SubtitleExportDialog',fail)
    monkeypatch.setattr(studio_ass_flow,'studio_message_box',lambda *a,**kw:messages.append(a))
    page.studio_export_button.click()
    assert messages and 'controlled subtitle setup failure' in str(messages)
