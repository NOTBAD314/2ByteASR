"""2026-11-11: the cue list's filter track, bulk-review strip and stepper."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _page(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page.resize(1500, 900)
    page.show()
    app.processEvents()
    return app, page


def test_filters_share_one_track_and_the_stepper_moves_both_ways(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        for button in page.cue_filter_buttons.values():
            if button.parentWidget() is page.cue_filter_track:
                continue
            # Only the three visible filters live in the track.
            assert button not in page.cue_filter_track.findChildren(type(button))
        assert {key for key, button in page.cue_filter_buttons.items()
                if button.parentWidget() is page.cue_filter_track} == {"all", "priority", "critical"}
        steps = []
        page._step_cue = steps.append
        page.cue_step_previous.click()
        page.cue_step_next.click()
        assert steps == [-1, 1]
        assert page.cue_step_previous.accessibleName() and page.cue_step_next.accessibleName()
    finally:
        page.close_page()


def test_bulk_review_strip_shows_only_while_its_button_is_enabled(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        strip, button = page.confirm_all_reviews_strip, page.confirm_all_reviews_button
        assert strip.isHidden() and not button.isEnabled()
        button.setEnabled(True)
        app.processEvents()
        assert not strip.isHidden()
        button.setEnabled(False)
        app.processEvents()
        assert strip.isHidden()
    finally:
        page.close_page()
