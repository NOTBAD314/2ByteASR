"""A hidden Video form must not shape every caption after selecting all."""
from unittest.mock import patch
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.timeline.selection_scope import SelectionScope
from tests.test_motion_workflow_ui import make_page, close


def test_hidden_bulk_refresh_defers_geometry_until_video_tab_is_shown(tmp_path):
    app, page = make_page(tmp_path)
    try:
        page.project.cues.extend(StudioCue(str(i), i*1000, i*1000+900, f'字幕{i}', 'S01')
                                 for i in range(10, 70))
        page._cue_lookup = {c.id: c for c in page.project.cues}
        page.cue_model.set_project(page.project)
        page.timeline.set_project(page.project)
        ids = [c.id for c in page.project.cues]
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(ids, 'a'))
        page.context_drawer.setCurrentIndex(1)
        panel = page.caption_transform_panel
        assert not panel.isVisible()
        with patch('twobyteasr.caption_style.caption_transform_panel.GeometryBatch') as batch:
            panel.refresh()
            batch.assert_not_called()
        assert panel._needs_refresh
        page.show()
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        owner = panel
        while owner is not None:
            owner.show()
            owner = owner.parentWidget()
        app.processEvents()
        panel.refresh()
        assert not panel._needs_refresh
        assert panel.controls['position_x'].isEnabled()
    finally:
        close(page)
