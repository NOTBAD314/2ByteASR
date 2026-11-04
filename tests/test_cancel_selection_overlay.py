import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_studio_style_controller import _page, _finish


@pytest.mark.parametrize('layer', ['original', 'translation'])
def test_cancel_selection_removes_transform_from_widget_and_native_video(tmp_path, monkeypatch, layer):
    app, page = _page(tmp_path, monkeypatch)
    removed = []
    monkeypatch.setattr(page.video, 'remove_compositor_overlay', lambda overlay_id, **kw: removed.append(overlay_id))
    try:
        page.show()
        app.processEvents()
        page.timeline.active_subtitle_layer = layer
        ancestor = page.position_overlay.parentWidget()
        while ancestor is not None:
            ancestor.show()
            ancestor = ancestor.parentWidget()
        page.position_overlay.show()
        assert page.position_overlay.isVisible()
        if layer == 'translation':
            page.cue_controller._mirror_clock_selection('')
            assert page.selected_cue_id == 'a' and page.position_overlay.isVisible()
        before = page.project.to_dict()
        page.cue_controller.cancel_selection()
        assert page.selected_cue_id == ''
        assert not page.position_overlay.isVisible()
        assert page.video.TRANSFORM_OVERLAY_ID in removed
        page.cue_controller.sync_playhead_target(page.timeline.playhead_ms)
        assert page.selected_cue_id == '' and not page.position_overlay.isVisible()
        assert page.project.to_dict() == before
    finally:
        _finish(page)
