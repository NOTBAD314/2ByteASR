"""Measured speech handoffs and compact stable lanes, 2026-10-09."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from twobyteasr.subtitle_rules.display_timing import project_display_tail_plan, protect_runtime_display_tails
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def project():
    p = SubtitleProject(media=StudioMedia('', duration_ms=6000), cues=[
        StudioCue('a', 3717, 4850, '我会了', speaker_id='S02', evidence_refs=['a', 'b']),
        StudioCue('b', 4533, 6450, '现在很多', speaker_id='S01', evidence_refs=['a', 'b'])])
    p.asr_evidence = {
        'a': dict(speaker_id='S02', moss_start=3.71, moss_end=4.65,
                  final_timing_owner='FireRed', words=[
                      dict(text='我', start_ms=3740, end_ms=3940),
                      dict(text='会', start_ms=3940, end_ms=4180),
                      dict(text='了', start_ms=4180, end_ms=4540)]),
        'b': dict(speaker_id='S01', moss_start=4.45, moss_end=5.91,
                  final_timing_owner='FireRed', words=[
                      dict(text='现在', start_ms=4540, end_ms=4740),
                      dict(text='很多', start_ms=4740, end_ms=5060)])}
    return p


def test_exact_words_override_parent_overlap_without_cutting_last_word():
    p = project(); before = deepcopy(p)
    ends, audit = project_display_tail_plan(p)
    assert ends == {'a': 4540}  # Display of incoming starts 7 ms early.
    assert audit['pairs_before'][0]['evidence_kind'] == 'measured_cue_words'
    assert p == before


def test_actual_word_overlap_is_preserved():
    p = project(); p.asr_evidence['b']['words'][0]['start_ms'] = 4400
    ends, audit = project_display_tail_plan(p)
    assert ends == {'a': 4540}  # Keep actual 4400..4540 speech; drop only its tail.
    assert audit['pairs_before'][0]['classification'] == 'source_overlap_unverified'


def test_confirmed_independent_overlap_overrides_mono_word_boundaries():
    p = project(); p.asr_evidence['a']['verified_overlap_with'] = ['b']
    assert project_display_tail_plan(p)[0] == {}


@pytest.mark.parametrize('kind', ['missing', 'estimated', 'partial'])
def test_incomplete_or_estimated_words_do_not_guess_away_source_overlap(kind):
    p = project()
    if kind == 'missing':
        p.asr_evidence['a'].pop('words')
    elif kind == 'partial':
        p.asr_evidence['a']['words'] = p.asr_evidence['a']['words'][-1:]
    else:
        p.asr_evidence['a']['caption_arbitration'] = {
            'word_timing': {'basis': 'uniform_display_estimate'}}
    assert project_display_tail_plan(p)[0] == {}


def test_current_clock_words_survive_rigid_move_and_inner_spelling_edit():
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, sync_caption_interval_words
    p = project(); ensure_independent_captions(p)
    for c in p.cues:
        before = (c.start_ms, c.end_ms)
        c.start_ms += 10000; c.end_ms += 10000
        sync_caption_interval_words(p, c, before)
    p.cues[0].text = '我惠了'  # Saved first and last acoustic tokens unchanged.
    ends, _ = project_display_tail_plan(p)
    assert ends == {'a': 14540}


def test_runtime_uses_same_exact_word_policy():
    p = project()
    cues = [SimpleNamespace(cue_id=c.id, start=c.start_ms/1000, end=c.end_ms/1000,
                            text=c.text, speaker=c.speaker_id) for c in p.cues]
    segments = [SimpleNamespace(start=e['moss_start'], end=e['moss_end'], speaker=e['speaker_id'],
        moss_start=e['moss_start'], moss_end=e['moss_end'], words=e['words'],
        final_timing_owner=e['final_timing_owner']) for e in p.asr_evidence.values()]
    report = protect_runtime_display_tails(cues, segments)
    assert cues[0].end == 4.540
    assert report[0]['evidence_kind'] == 'measured_cue_words'


def test_tail_extension_never_introduces_cross_speaker_overlap():
    from twobyteasr.subtitle_rules.timing import extend_cue_tails_by_speaker
    cues = [SimpleNamespace(cue_id=1, start=0., end=1., speaker='A'),
            SimpleNamespace(cue_id=2, start=1.05, end=2., speaker='B')]
    extend_cue_tails_by_speaker(cues, 3., 60.)
    assert cues[0].end == 1.05


def test_tail_extension_keeps_real_overlap_without_extending_it():
    from twobyteasr.subtitle_rules.timing import extend_cue_tails_by_speaker
    cues = [SimpleNamespace(cue_id=1, start=0., end=1., speaker='A'),
            SimpleNamespace(cue_id=2, start=.9, end=2., speaker='B')]
    extend_cue_tails_by_speaker(cues, 3., 60.)
    assert cues[0].end == 1.


def test_tall_incoming_caption_does_not_inflate_gap_below_it():
    from twobyteasr.caption_style.subtitle_stacking import compute_stack_layout
    def resolved(cue):
        return SimpleNamespace(style=SimpleNamespace(font_size=50, scale_y=100,
            outline_width=0, shadow=0), line_count=1,
            recipe=SimpleNamespace(layout={'lineHeightPx': 50 if cue.id=='a' else 180}))
    cues = [SimpleNamespace(id='a', start_ms=0, end_ms=2000),
            SimpleNamespace(id='b', start_ms=1000, end_ms=3000)]
    layout = compute_stack_layout(cues, resolve_one=resolved, play_res_y=1080)
    assert layout.offset_for('a') == 0
    assert layout.offset_for('b') == 66  # Earlier ink 50 + visible gap 16.


def test_manual_obstacle_uses_its_actual_edge_without_a_full_extra_band():
    from twobyteasr.caption_style.subtitle_stacking import compute_stack_layout
    cues = [SimpleNamespace(id='a', start_ms=0, end_ms=2000, transform={'position_locked':True}),
            SimpleNamespace(id='b', start_ms=1000, end_ms=3000, transform={})]
    def resolved(cue):
        return SimpleNamespace(style=SimpleNamespace(font_size=50, scale_y=100,
            outline_width=0, shadow=0, position_y=1010 if cue.id=='a' else 1040),
            line_count=1, recipe=SimpleNamespace(layout={'lineHeightPx':50 if cue.id=='a' else 180}))
    layout = compute_stack_layout(cues, resolve_one=resolved, play_res_y=1080)
    assert layout.offset_for('a') == 0
    assert layout.offset_for('b') == 96


def test_faint_shadow_halo_does_not_create_a_large_empty_band():
    from twobyteasr.caption_style.subtitle_stacking import compute_stack_layout
    rows=[SimpleNamespace(id='a',start_ms=0,end_ms=2000),
          SimpleNamespace(id='b',start_ms=1000,end_ms=3000)]
    style=SimpleNamespace(font_size=50,scale_y=100,outline_width=8,shadow=9)
    recipe=SimpleNamespace(layout={'lineHeightPx':50},outline={'shadow':{
        'enabled':True,'offset_y':7,'blur':14,'spread':3}})
    result=compute_stack_layout(rows,resolve_one=lambda _:SimpleNamespace(
        style=style,recipe=recipe,line_count=1),play_res_y=1080)
    assert result.offset_for('b')==84  # 50 + 2*9 solid outsets + 16 gap.


def test_layout_review_survives_background_save_of_view_preferences():
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio.subtitle_layout_ui import SubtitleLayoutPreview
    app=QApplication.instance() or QApplication([])
    page=QWidget(); page.project=project(); page.undo_stack=QUndoStack(page)
    page._changed=lambda:None
    page._show_studio_hint=lambda message:pytest.fail(message)
    dialog=SubtitleLayoutPreview(page, ['a','b'])
    page.project.studio_state.update(playhead_ms=4650,last_selected_cue='b',zoom=649,
                                    scroll_ms=3655,layout={'upper_sizes':[300,790]})
    assert dialog.apply()
    assert page.undo_stack.count()==1
    assert page.project.studio_state['playhead_ms']==4650
    page.close()


@pytest.mark.parametrize('automatic,geometry', [(True,True),(False,True),(True,False)])
def test_batch_preset_automatically_avoids_overlap_in_one_undo(automatic,geometry):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.exports.preset_application import preset_command
    from twobyteasr.caption_style.style_resolution import resolve_cue_visual
    app=QApplication.instance() or QApplication([])
    p=project(); p.studio_state['auto_subtitle_stacking']=automatic
    for c in p.cues:c.transform={'position_x':960,'position_y':1035}
    before=deepcopy(p.cues)
    command=preset_command(p,['a','b'],dict(id='test',name='Test',font_size=98,
        font_family='Microsoft YaHei',position_x=960,position_y=1035),apply_geometry=geometry)
    stack=QUndoStack();stack.push(command)
    ys=[resolve_cue_visual(p,c).style.position_y for c in p.cues]
    if automatic and geometry:
        assert ys[0]>ys[1] and 50<ys[0]-ys[1]<160
    else:assert ys==[1035,1035]
    assert stack.count()==1
    stack.undo();assert [c.transform for c in p.cues]==[c.transform for c in before]


def test_handoff_preview_rejects_text_edits_after_word_boundary_review():
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio.display_handoff_ui import DisplayHandoffPreview
    app=QApplication.instance() or QApplication([])
    page=QWidget();page.project=project();page.undo_stack=QUndoStack(page)
    hints=[];page._show_studio_hint=hints.append;page._changed=lambda:None
    dialog=DisplayHandoffPreview(page)
    page.project.cues[0].text='我完全会了'
    dialog.apply()
    assert hints and page.undo_stack.count()==0
    assert page.project.cues[0].end_ms==4850
    page.close()
