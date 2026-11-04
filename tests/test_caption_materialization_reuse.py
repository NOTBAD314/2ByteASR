"""A local MD mark edit rebuilds one caption (Codex 2026-10-24, ported onto the daily engine).

The daily line keeps its incremental ``materialize_captions`` (2026-10-22 stall
stage 1); Codex's own ``materialize_caption_project(revision, previous, cue_ids=...)``
was not carried over, so these checks drive the daily engine with one revision
store, as the Studio does.
"""
from dataclasses import asdict

from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.projects.studio_runtime_state import DirtyDomain as D, StateDelta
from twobyteasr.rendering.caption_playback_cache import materialize_captions


def _commit(store, dirty, ids, revision):
    store.consume(StateDelta("t", dirty | D.AUTOSAVE, frozenset(ids), frozenset(), (), "", "", revision))


def _rows(materialized):
    return [asdict(cue) for cue in materialized.project.cues]


def test_local_marks_edit_only_relayouts_one_cue():
    QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue(str(i),i*1000,(i+1)*1000,'相同字幕') for i in range(100)])
    p.validate()
    store=StudioRevisionStore(p)
    first,_,reason=materialize_captions(store.render)
    assert reason=='first'
    p.cues[5].appearance_override={'text_marks':[{'start':0,'end':2,'bold':True}]}
    _commit(store,D.CUE_CONTENT,['5'],11)
    second,reused,reason=materialize_captions(store.render,first)
    assert reason=='' and '5' not in reused and len(reused)==99
    assert _rows(second)==_rows(materialize_captions(store.render)[0])
    assert not first.project.cues[5].appearance_override
    assert second.project.cues[5].appearance_override['text_marks'][0]['bold'] is True
    p.styles[0].font_size+=5
    _commit(store,D.CUE_STYLE,[],12)
    third,_,_=materialize_captions(store.render,second)
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    assert build_visual_cue_snapshot(third.project,'0').font_size == p.styles[0].font_size
    assert build_visual_cue_snapshot(second.project,'0').font_size == p.styles[0].font_size-5
