"""Repeated inspector changes reuse scope identities and preserve geometry."""
from tests.test_studio_style_controller import _page, _finish
from twobyteasr.caption_style.style_resolution import resolve_cue_visual


def test_repeated_all_scope_style_edits_do_not_accumulate_derived_recipes(tmp_path, monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.style_scope.setCurrentIndex(page.style_scope.findData('all'))
        original=[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues]
        counts=[]
        for size in (51,52,53,54):
            page.style_font_size.setValue(size);page._commit_style_now()
            counts.append((len(page.project.styles),len(page.project.style_recipes)))
            assert all(resolve_cue_visual(page.project,c).style.font_size==size for c in page.project.cues)
        assert counts[1:]==[counts[0]]*3,counts
        assert original==[(c.id,c.text,c.start_ms,c.end_ms) for c in page.project.cues]
        page.undo_stack.undo(); assert resolve_cue_visual(page.project,page.project.cues[0]).style.font_size==53
        page.undo_stack.redo(); assert resolve_cue_visual(page.project,page.project.cues[0]).style.font_size==54
    finally:_finish(page)
