"""Home entry and Studio workflow regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.app.home_studio_entry import StudioEntryCard, studio_paper_colors
from twobyteasr.design.ui_theme import theme_definition

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def test_paper_card_background_click_and_keyboard_enter(app):
    card = StudioEntryCard(); card.resize(640, 420); card.show()
    spy = QSignalSpy(card.clicked)
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(480, 80))
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert spy.count() == 2
    paper, _, _, _, _ = studio_paper_colors(theme_definition("warm"))
    assert paper != theme_definition("warm").accent_soft
    card.close()


def test_drop_into_new_v3_v4_preserves_destination_time_and_undo(app, tmp_path, monkeypatch):
    from twobyteasr.media.media_ingest import MediaIngestResult
    from twobyteasr.timeline.studio_media_pool import create_video_track
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    page = SubtitleStudioPage()
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path/'base.mp4'), duration_ms=10000))
    project.validate(); create_video_track(project)
    page.project = project; page.timeline.set_project(project)
    for name in ('_refresh_edit_playback_state', '_sync_multitrack_preview_at', '_generate_project_waveforms', '_sync_video_empty_state'):
        monkeypatch.setattr(page, name, lambda *a: None)
    for generation, expected in ((1, 'V3'), (2, 'V4')):
        source = str(tmp_path/f'clip{generation}.mp4')
        page._media_ingest_generation = generation
        page._media_ingest_project_token = project.project_id
        page._pending_media_path = source
        page._pending_media_mode = 'timeline'
        page._pending_media_track_id = 'new'
        page._pending_media_timeline_ms = 1234
        page.timeline.playhead_ms = 8000  # Playback moved while ingest ran.
        page._media_ingest_ready(MediaIngestResult(generation, project.project_id, source,
            duration_ms=3000, width=1920, height=1080, has_video=True, has_audio=True))
        track = next(t for t in project.video_tracks if t.id == expected)
        assert track.clips[0].timeline_in_ms == 1234
    page.undo_stack.undo()
    assert [t.id for t in project.video_tracks] == ['V1', 'V2', 'V3']
    page.close_page()

