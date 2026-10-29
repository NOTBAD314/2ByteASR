"""Canonical edits reuse the index; detached views and timing still refresh."""
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.projects.studio_runtime_state import state_for, DirtyDomain


def project():
    p = SubtitleProject(StudioMedia("", duration_ms=3000), cues=[StudioCue("c", 1000, 2000, "古龙")],
                        render_settings={"_cue_domain": "timeline"})
    p.validate()
    return p


def test_canonical_text_edit_is_visible_without_rebuilding_time_index(monkeypatch):
    p = project()
    state = state_for(p)
    assert state._view_cues is p.cues
    def unexpected(*args):
        raise AssertionError("a text-only edit must not sort and reindex every caption")
    monkeypatch.setattr(state, "reindex_cues", unexpected)
    with state.transaction(p, action_id="test", dirty=DirtyDomain.CUE_CONTENT, affected_cue_ids=("c",)):
        p.cues[0].text = "骨龙"
    assert state.cues_at(1500)[0].text == "骨龙"
    assert state.view_cue("c").text == "骨龙"


def test_timing_edits_still_rebuild_index(monkeypatch):
    p = project()
    state = state_for(p)
    reindex = state.reindex_cues
    calls = []
    def counted(project):
        calls.append(True)
        reindex(project)
    monkeypatch.setattr(state, "reindex_cues", counted)
    with state.transaction(p, action_id="move", dirty=DirtyDomain.CUE_TIMING, affected_cue_ids=("c",)):
        p.cues[0].start_ms = 1700
    assert calls == [True]
    assert not state.cues_at(1500)


def test_detached_text_projection_is_not_skipped(monkeypatch):
    p = project()
    state = state_for(p)
    state._view_cues = list(p.cues)  # distinct projected list: the safe fallback
    reindex = state.reindex_cues
    calls = []
    def counted(project):
        calls.append(True)
        reindex(project)
    monkeypatch.setattr(state, "reindex_cues", counted)
    with state.transaction(p, action_id="text", dirty=DirtyDomain.CUE_CONTENT, affected_cue_ids=("c",)):
        p.cues[0].text = "骨龙"
    assert calls == [True] and state.view_cue("c").text == "骨龙"
