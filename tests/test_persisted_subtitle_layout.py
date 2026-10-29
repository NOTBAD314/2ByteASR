"""Initial allocation and manual anchors across real render/persistence paths."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, SubtitleStyle,
    load_project, save_project, project_from_runtime_cues,
)
from twobyteasr.caption_style.subtitle_stacking import initialize_project_layout, rearrange_subtitles_command
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.rendering.ass_compiler import compile_ass, compile_ass_revision
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.rendering.caption_playback_cache import materialize_caption_project
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand


@pytest.fixture(scope='module', autouse=True)
def app():
    value = QApplication.instance() or QApplication([])
    yield value


def project():
    return SubtitleProject(media=StudioMedia('missing.mp4', duration_ms=5000),
        speakers=[StudioSpeaker('S00'), StudioSpeaker('S01'), StudioSpeaker('S02')],
        styles=[SubtitleStyle('default','Default', font_size=90, outline_width=8,
                              shadow=0, margin_v=43)],
        cues=[StudioCue('earlier', 0, 2000, '非常尴尬的一幕', speaker_id='S01'),
              StudioCue('later', 500, 2600, '好亏啊但能拉要不要考虑拉一手', speaker_id='S00')])


def anchors(p):
    return {c.id: (resolve_cue_visual(p,c).style.position_x,
                   resolve_cue_visual(p,c).style.position_y) for c in p.cues}


def test_initial_layout_follows_time_keeps_bottom_compact_and_saves(tmp_path):
    p = project()
    before = [(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]
    layout = initialize_project_layout(p)
    assert not layout.warnings
    assert anchors(p)['earlier'][1] == 1037
    assert 70 < anchors(p)['earlier'][1] - anchors(p)['later'][1] < 140
    assert [(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues] == before
    expected = anchors(p)
    save_project(p,tmp_path/'layout.2byteproj')
    restored = load_project(tmp_path/'layout.2byteproj')
    assert anchors(restored) == expected
    assert restored.cues[0].transform['initial_layout']['source'] == 'temporal_overlap'


def test_manual_order_is_authoritative_across_snapshot_ass_revision_and_reopen(tmp_path, monkeypatch):
    p = project()
    initialize_project_layout(p)
    undo = QUndoStack()
    for c, y in zip(p.cues, (900, 1010)):
        transform = deepcopy(c.transform)
        transform.update(position_x=960, position_y=y)
        undo.push(SetCueFieldsCommand(p,c.id,{'transform':transform},'移动字幕'))
    expected = anchors(p)
    assert expected['earlier'][1] < expected['later'][1]  # Swapped manual order is allowed.
    # Neither render nor reopen may call the allocation operation again.
    import twobyteasr.caption_style.subtitle_stacking as stacking
    monkeypatch.setattr(stacking,'compute_stack_layout',lambda *_a,**_k: pytest.fail('render reallocated layout'))
    for width,height in [(1920,1080),(1000,700),(800,450)]:
        assert {c.id: build_visual_cue_snapshot(p,c.id,width=width,height=height).position_y
                for c in p.cues} == {'earlier':900,'later':1010}
    revision = StudioRevisionStore(p).render
    worker = materialize_caption_project(revision)
    assert anchors(worker) == expected
    assert compile_ass(p) == compile_ass_revision(revision)
    save_project(p,tmp_path/'manual.2byteproj')
    restored = load_project(tmp_path/'manual.2byteproj')
    assert anchors(restored) == expected
    assert compile_ass(restored) == compile_ass(p)


def test_position_edit_does_not_move_peer_and_nonposition_edits_keep_anchor():
    p = project()
    initialize_project_layout(p)
    old = anchors(p)
    p.cues[1].transform.update(position_x=700,position_y=1060)
    p.cues[0].text = '改字后仍保持原位置'
    p.speakers[0].name = '中文姓名'
    p.styles[0].font_size = 110
    assert anchors(p)['earlier'] == old['earlier']
    assert anchors(p)['later'] == (700,1060)
    # Repeated generation initialization only handles unarranged content.
    assert initialize_project_layout(p).offsets == {}
    assert anchors(p)['earlier'] == old['earlier']


def test_live_drag_preview_uses_pointer_anchor_without_committing_or_reoffsetting():
    from twobyteasr.projects.studio_revisions import preview_render_revision
    p = project()
    initialize_project_layout(p)
    p.cues[1].transform.update(position_x=950,position_y=980)
    original = deepcopy(p.cues)
    revision = StudioRevisionStore(p).render
    preview = preview_render_revision(revision,
        transform_overrides={'later':{'position_x':700,'position_y':820}})
    worker = materialize_caption_project(preview)
    assert anchors(worker)['later'] == (700,820)
    assert p.cues == original
    assert anchors(materialize_caption_project(revision))['later'] == (950,980)


def test_new_third_cue_uses_actual_overlap_without_moving_existing_cues():
    p = project()
    initialize_project_layout(p)
    old = anchors(p)
    p.cues.extend([StudioCue('third',800,1800,'第三个重叠人',speaker_id='S02'),
                   StudioCue('sequential',3000,4200,'没有重叠',speaker_id='S02')])
    initialize_project_layout(p)
    value = anchors(p)
    assert all(value[key] == point for key,point in old.items())
    assert value['third'][1] < value['later'][1]
    assert value['sequential'][1] == value['earlier'][1]


def test_explicit_relayout_is_scoped_and_one_undo_step():
    p = project()
    initialize_project_layout(p)
    p.cues[0].transform.update(position_x=800,position_y=1000)
    p.cues[1].transform.update(position_x=950,position_y=990)
    before = deepcopy(p.cues)
    undo = QUndoStack()
    command, _ = rearrange_subtitles_command(p,['later'])
    assert command is not None
    undo.push(command)
    assert undo.count() == 1
    assert p.cues[0] == before[0]
    after = deepcopy(p.cues)
    assert 'position_y' not in p.cues[1].transform
    assert anchors(p)['later'][1] < 1000
    undo.undo()
    assert [c.transform for c in p.cues] == [c.transform for c in before]
    assert [(c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues] == [
        (c.text,c.start_ms,c.end_ms,c.speaker_id) for c in before]
    undo.redo()
    assert [c.transform for c in p.cues] == [c.transform for c in after]


def test_legacy_project_does_not_gain_layout_from_render_or_load(tmp_path):
    p = project()
    before = p.to_dict()
    compile_ass(p)
    build_visual_cue_snapshot(p,'earlier')
    assert p.to_dict() == before
    assert all('initial_layout' not in c.transform for c in p.cues)
    save_project(p,tmp_path/'legacy.2byteproj')
    restored = load_project(tmp_path/'legacy.2byteproj')
    assert all('initial_layout' not in c.transform for c in restored.cues)


def test_real_generation_initializes_and_plain_runtime_metadata_is_preserved():
    rows = [SimpleNamespace(cue_id='a',start=0.,end=2.,text='第一条',speaker='S01'),
            SimpleNamespace(cue_id='b',start=.5,end=2.6,text='第二条',speaker='S00')]
    p = project_from_runtime_cues('missing.mp4',rows, media_identity={'duration_ms':3000})
    assert all('initial_layout' in c.transform for c in p.cues)
    assert anchors(p)['a'][1] > anchors(p)['b'][1]
    assert all(c.original_text == c.text for c in p.cues)


def test_visible_ink_bounds_produce_compact_real_live_raster_gap():
    from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
    from twobyteasr.studio.selection_geometry import image_bounds
    p = project()
    initialize_project_layout(p)
    bounds = {}
    for c in p.cues:
        snapshot = build_visual_cue_snapshot(p,c.id)
        image = render_live_snapshot(snapshot,width=1920,height=1080)
        bounds[c.id] = image_bounds(image)
    top = bounds['later']; bottom = bounds['earlier']
    gap = bottom[1] - (top[1]+top[3])
    assert 10 <= gap <= 24, (gap,bounds)
    assert 32 <= 1080-(bottom[1]+bottom[3]) <= 54
