"""Regression coverage for stable cue instances and save-only bulk review."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import time

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia,
    StudioCue, StudioSpeaker, save_project, load_project)
from twobyteasr.caption_style.collision_layout import (layout_schedule,
    ProjectCollisionLayout, project_layout_schedule)
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.subtitle_rules.current_issues import (
    current_issue_view, pending_review_changes, invalidate, DECISIONS, acknowledged_issue_views)
from twobyteasr.subtitle_rules.studio_qc import QCIssue, QCResult, QCSeverity, QCCategory
from twobyteasr.studio.caption_editor import IssueDecisionsCommand


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project():
    return SubtitleProject(media=StudioMedia('', duration_ms=6000),
        speakers=[StudioSpeaker('S0'), StudioSpeaker('S1'), StudioSpeaker('S2')], cues=[
            StudioCue('a', 0, 3000, 'A的完整文字', speaker_id='S0'),
            StudioCue('b', 1000, 5000, 'B的完整文字', speaker_id='S1'),
            StudioCue('c', 3500, 4500, 'C的完整文字', speaker_id='S2')])


def test_reuse_hole_without_moving_survivor():
    p = project()
    ss = [build_visual_cue_snapshot(p, c.id) for c in p.cues]
    schedule = layout_schedule(iter(ss), bounds_for=lambda s: QRectF(500, 900, 700, 60))
    assert schedule == {'a': [(0, 3000, 0.)], 'b': [(1000, 5000, 68.)],
                        'c': [(3500, 4500, 0.)]}
    assert layout_schedule(reversed(ss), bounds_for=lambda s: QRectF(500, 900, 700, 60)) == schedule


def test_larger_newcomer_uses_another_slot_and_preserves_survivor():
    p=project();ss=[build_visual_cue_snapshot(p,c.id) for c in p.cues]
    def bounds(snapshot):
        height=180 if snapshot.cue_id=='c' else 60
        return QRectF(500,1000-height,700,height)
    plan=layout_schedule(ss,bounds_for=bounds)
    assert plan['b']==[(1000,5000,68.)]
    assert plan['c'][0][2] > plan['b'][0][2]


def test_top_anchored_subtitles_use_free_space_below_and_keep_it():
    from twobyteasr.caption_style.collision_layout import shifted_snapshot, visual_bounds
    from twobyteasr.rendering.ass_compiler import compile_ass
    p=project();p.styles[0].alignment=8;p.styles[0].margin_v=10
    plan=project_layout_schedule(p)
    assert plan['b'][0][2]<0 and plan['c'][0][2]==0
    for c in p.cues:
        box=visual_bounds(shifted_snapshot(build_visual_cue_snapshot(p,c.id),plan[c.id][0][2]))
        assert box.top()>=0 and box.bottom()<=1080
    assert 'Dialogue:' in compile_ass(p)


def test_deleted_occupant_is_invalidated_and_undo_restores_plan():
    from twobyteasr.timeline.studio_commands import delete_cues_command
    p=project();cache=ProjectCollisionLayout()
    revision=SimpleNamespace(mapping_revision=1,visual_revision=1)
    before=cache.for_cues(p,[p.cues[1]],revision).offsets['b']
    command=delete_cues_command(p,['a']);command.redo()
    revision.mapping_revision+=1
    assert cache.for_cues(p,[next(c for c in p.cues if c.id=='b')],revision).offsets['b']==0
    command.undo();revision.mapping_revision+=1
    assert cache.for_cues(p,[next(c for c in p.cues if c.id=='b')],revision).offsets['b']==before


@pytest.mark.parametrize('ends', [(3000, 5000, 2200), (5000, 2500, 4000), (2500, 4000, 5000)])
def test_three_end_orders_never_split_an_instance(ends):
    p = project()
    for c, start, end in zip(p.cues, (0, 1000, 1500), ends):
        c.start_ms, c.end_ms = start, end
    schedule = project_layout_schedule(p)
    assert all(len(spans) == 1 for spans in schedule.values())


def test_direct_seek_uses_ended_peers_and_cached_geometry(monkeypatch):
    import twobyteasr.caption_style.collision_layout as module
    p = project()
    cache = ProjectCollisionLayout()
    revision = SimpleNamespace(mapping_revision=1, visual_revision=1)
    # First request is AFTER A ended, yet B must keep the slot above it.
    first = cache.for_cues(p, [p.cues[1]], revision)
    assert first.offsets['b'] > 0
    assert 'c' not in first.offsets  # Future captions are not measured early.
    def unexpected(*args, **kwargs):
        raise AssertionError('ordinary clock/selection query rebuilt layout')
    monkeypatch.setattr(module, 'build_visual_cue_snapshot', unexpected, raising=False)
    from twobyteasr.caption_style import visual_snapshot
    monkeypatch.setattr(visual_snapshot, 'build_visual_cue_snapshot', unexpected)
    for _ in range(100):
        assert cache.for_cues(p, [p.cues[1]], revision) == first


def issues(p):
    return QCResult({c.id: (QCIssue('synthetic_check',
        QCSeverity.CRITICAL if c.id == 'a' else QCSeverity.WARNING,
        QCCategory.TEXT, c.id, '检查当前文字', '针对当前字幕的检查'),) for c in p.cues})


def test_bulk_review_preserves_data_roundtrips_undo_and_local_change(tmp_path):
    p = project(); p._qc_result = issues(p)
    p.studio_state[DECISIONS] = {}  # Existing saved empty buckets keep cache identity on undo.
    before_view = current_issue_view(p)
    original = deepcopy(p.to_dict())
    changes, ids, count = pending_review_changes(p)
    assert ids == {'a','b','c'} and count == 3
    stack = QUndoStack(); refreshes = []
    stack.push(IssueDecisionsCommand(p, changes, lambda: refreshes.append(1),
        prepared_issue_views=acknowledged_issue_views(p, changes)))
    assert not current_issue_view(p).by_cue
    assert p.to_dict()['cues'] == original['cues']
    assert p.asr_evidence == original['asr_evidence']
    assert all(row['action'] == 'reviewed_keep_current' for row in p.studio_state[DECISIONS].values())
    stack.undo(); assert current_issue_view(p) is before_view
    assert current_issue_view(p).counts() == {'critical':1, 'priority':2}
    stack.redo(); assert not current_issue_view(p).by_cue
    assert len(refreshes) == 3 and stack.count() == 1
    saved = save_project(p, tmp_path/'reviewed.2byteproj')
    reopened = load_project(saved); reopened._qc_result = issues(reopened)
    assert not current_issue_view(reopened).by_cue
    reopened.cues[0].text += '已修改'
    reopened._qc_result = issues(reopened); invalidate(reopened, {'a'})
    assert set(current_issue_view(reopened).by_cue) == {'a'}


def test_ten_thousand_bulk_review_is_one_refresh():
    p = project()
    p.cues = [StudioCue(str(i), i*3000, i*3000+2500, '已有完整字幕') for i in range(10000)]
    p._qc_result = issues(p)
    current_issue_view(p)
    start = time.perf_counter()
    changes, ids, count = pending_review_changes(p)
    refreshes = []
    stack = QUndoStack(); stack.push(IssueDecisionsCommand(p, changes, lambda: refreshes.append(1)))
    assert len(ids) == count == 10000 and refreshes == [1]
    assert not current_issue_view(p).by_cue
    assert time.perf_counter()-start < 5


def test_long_connected_overlap_component_prepares_only_reached_events(monkeypatch):
    from twobyteasr.caption_style import visual_snapshot
    p=project()
    p.cues=[StudioCue(str(i), i*1000, i*1000+1500, '相同字幕', speaker_id=str(i%3)) for i in range(10000)]
    original=visual_snapshot.build_visual_cue_snapshot
    prepared=[]
    def measured(project, cue_id, *args, **kwargs):
        prepared.append(cue_id)
        return original(project, cue_id, *args, **kwargs)
    monkeypatch.setattr(visual_snapshot, 'build_visual_cue_snapshot', measured)
    revision=SimpleNamespace(mapping_revision=1, visual_revision=1)
    cache=ProjectCollisionLayout()
    initial=cache.for_cues(p,[p.cues[2]],revision)
    assert prepared==['0','1','2'] and set(initial.offsets)=={'2'}
    for _ in range(100):assert cache.for_cues(p,[p.cues[2]],revision)==initial
    assert len(prepared)==3
    continued=cache.for_cues(p,[p.cues[3]],revision)
    direct=ProjectCollisionLayout().for_cues(p,[p.cues[3]],revision)
    assert continued==direct


def test_locked_acoustic_times_survive_automatic_compensation():
    import subtitle_core as core
    from twobyteasr.subtitle_rules.timing import normalize_cue_times, extend_cue_tails_by_speaker
    cues=[core.SubtitleCue(1, 0., .3, '人工确认完整发声', speaker='A', timing_locked=True),
          core.SubtitleCue(2, .4, 1., '下一句', speaker='B')]
    normalize_cue_times(cues,60);extend_cue_tails_by_speaker(cues,3.,60)
    assert cues[0].start==0. and cues[0].end==.3


def test_compensation_and_endpoint_mapping_are_idempotent():
    import subtitle_core as core
    from twobyteasr.subtitle_rules.timing import (
        normalize_cue_times, extend_cue_tails_by_speaker, lock_cue_endpoints_to_frames)
    cues=[core.SubtitleCue(1, .101, 1.007, '第一句', speaker='A'),
          core.SubtitleCue(2, 1.4, 2.007, '第二句', speaker='B')]
    normalize_cue_times(cues,60)
    assert cues[0].end >= 1.007
    extend_cue_tails_by_speaker(cues,4.,60)
    first=[(c.start,c.end) for c in cues]
    for _ in range(5):
        extend_cue_tails_by_speaker(cues,4.,60)
        lock_cue_endpoints_to_frames(cues,60)
    assert [(c.start,c.end) for c in cues]==first


def test_bilingual_export_and_preview_have_identical_group_offsets():
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    p=project()
    p.studio_state['bilingual']={'mode':'bilingual','layout':'ink_v1'}
    p.generation_metadata['translations']={c.id:'Translation '+c.id for c in p.cues}
    schedule=project_layout_schedule(p)
    explicit=project_layout_schedule(p,project_display_cues(p))
    assert schedule==explicit and 'b#tr' in schedule
    assert schedule['b'][0][2]==schedule['b#tr'][0][2]
    cache=ProjectCollisionLayout()
    result=cache.for_cues(p,p.cues,SimpleNamespace(mapping_revision=1,visual_revision=1))
    assert all(result.offsets[k]==v[0][2] for k,v in schedule.items())


def test_explicit_locked_position_is_a_fixed_obstacle():
    from twobyteasr.caption_style.collision_layout import solve_layout
    p=project();p.cues=p.cues[:2]
    p.cues[1].transform={'position_locked':True,'position_x':960,'position_y':900}
    snapshots=[build_visual_cue_snapshot(p,c.id) for c in p.cues]
    result=solve_layout(snapshots)
    assert result.offsets['b']==0 and p.cues[1].transform['position_y']==900


def test_minimum_reading_time_never_pushes_next_turn_or_cuts_speech():
    from twobyteasr.subtitle_rules.timing import normalize_cue_times, relock_display_timing
    import subtitle_core as core
    cues = [core.SubtitleCue(1, 0., .3, '前一句文字比较长', speaker='A'),
            core.SubtitleCue(2, .4, 1., '是的', speaker='B')]
    normalize_cue_times(cues, 60)
    assert cues[0].end == .4 and cues[1].start == .4
    cues = [core.SubtitleCue(1, 0., 1.2, '真的同时说话', speaker='A'),
            core.SubtitleCue(2, .9, 1.6, '同时发声', speaker='B')]
    normalize_cue_times(cues, 60)
    assert cues[0].end >= 1.2 and cues[1].start == .9
    cues = [core.SubtitleCue(1, 0., 1., '上一句', speaker='A'),
            core.SubtitleCue(2, 1.4, 2., '下一句', speaker='B')]
    relock_display_timing(cues, 3., 60)
    assert cues[0].end == 1. and cues[1].start == 1.4


def test_half_open_runtime_and_ass_mapping_share_endpoint():
    from twobyteasr.projects.studio_runtime_state import state_for
    from twobyteasr.timeline.caption_frame_time import ass_frame_ms
    p = project(); p.cues[1].start_ms = p.cues[0].end_ms
    assert [c.id for c in state_for(p).cues_at(3000)] == ['b']
    for fps in (24, 30, 60, 30000/1001):
        assert ass_frame_ms(p.cues[0].end_ms, fps) == ass_frame_ms(p.cues[1].start_ms, fps)
