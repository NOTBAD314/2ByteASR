import threading
import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.bilingual_layout import CaptionPreparationCancelled, project_display_cues
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.rendering.caption_playback_cache import materialize_captions


def project():
    app = QApplication.instance() or QApplication([])
    p = SubtitleProject(media=StudioMedia(''), cues=[
        StudioCue(str(i), i * 1000, i * 1000 + 900, f'Caption {i}') for i in range(5)])
    p.validate()
    return app, p


def test_retired_preview_never_returns_a_partial_display_project():
    app, p = project()
    checks = []
    def cancelled():
        checks.append(1)
        return len(checks) >= 4
    with pytest.raises(CaptionPreparationCancelled):
        project_display_cues(p, cancel_check=cancelled)
    assert len(checks) == 4


def test_cancelled_worker_failure_does_not_start_full_inprocess_fallback(monkeypatch):
    from twobyteasr.caption_style import bilingual_layout
    app, p = project()
    revision = StudioRevisionStore(p).render
    stopped = threading.Event()
    def failed_builder(_revision):
        stopped.set()
        return None
    def forbidden(*args, **kwargs):
        raise AssertionError('retired job must not start the fallback')
    monkeypatch.setattr(bilingual_layout, 'project_display_cues', forbidden)
    with pytest.raises(CaptionPreparationCancelled):
        materialize_captions(revision, full_builder=failed_builder, cancel_check=stopped.is_set)
