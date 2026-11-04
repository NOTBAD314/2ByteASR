import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.app.teach_hints import TeachHintStore


def test_hint_shows_once_and_reset_restores_it(tmp_path):
    path = tmp_path / "teach-hints.json"
    first = TeachHintStore(path)
    assert first.should_show("studio")
    assert first.mark_shown("studio")
    second = TeachHintStore(path)
    assert not second.should_show("studio")
    second.reset()
    assert TeachHintStore(path).should_show("studio")


def test_unknown_hint_is_not_persisted(tmp_path):
    store = TeachHintStore(tmp_path / "teach-hints.json")
    assert not store.should_show("unknown")
    assert not store.mark_shown("unknown")
    assert not store.path.exists()


def test_studio_context_banner_shows_once_and_returns_after_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    page.project=SubtitleProject(media=StudioMedia(path="fixture.mp4"))
    page._refresh_studio_empty_state(rescan=False)
    page.show()
    page._show_teach_hint("studio")
    app.processEvents()
    assert page.teach_banner.isVisible()
    page.teach_banner.hide()
    page._show_teach_hint("studio")
    assert not page.teach_banner.isVisible()
    page._teach_hints.reset()
    page._session_teach_hints.clear()
    page._show_teach_hint("studio")
    assert page.teach_banner.isVisible()
    page.close_page()
    page.deleteLater()
