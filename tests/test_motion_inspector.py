"""User-visible stage composition, true karaoke clock, and persistence."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from tests.test_motion_workflow_ui import make_page, close
from tests.test_word_motion_workflow import fixture_project, app
from twobyteasr.effect_dsl import validate_effect, EffectValidationError
from twobyteasr.motion_application import motion_command
from twobyteasr.word_animation import build_word_animation
from twobyteasr.letter_motion import sample
from twobyteasr.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.studio_project import save_project, load_project
from twobyteasr.ass_compiler import compile_ass, compile_ass_revision


def test_stage_cards_keep_independent_choices_and_duration(tmp_path):
    app, page = make_page(tmp_path)
    try:
        inspector = page.motion_inspector
        assert page.context_drawer.tabToolTip(page.motion_tab_index) == '动效'
        assert not page.context_drawer.widget(1).isAncestorOf(page.motion_sample)
        assert page.context_drawer.widget(page.motion_tab_index).isAncestorOf(page.motion_sample)
        before = copy.deepcopy(page.project.to_dict())
        inspector.choose('exit', 'scale')
        inspector.tabs.setCurrentIndex(1); inspector.seconds.setValue(.65)
        inspector.choose('loop', 'loop_float')
        inspector.tabs.setCurrentIndex(2); inspector.seconds.setValue(1.8)
        inspector.choose('entry', 'soft_pop')
        inspector.tabs.setCurrentIndex(0); inspector.seconds.setValue(.45)
        inspector.choose('words', 'karaoke_wipe')
        for index in (3, 2, 0, 1, 3): inspector.tabs.setCurrentIndex(index)
        assert page.project.to_dict() == before
        page.motion_apply.click()
        effect = page.project.effects[page.project.cues[0].effect_id]
        assert (effect['entry']['type'], effect['entry']['duration']) == ('soft_pop', 450)
        assert (effect['exit']['type'], effect['exit']['duration']) == ('scale', 650)
        assert (effect['loop']['type'], effect['loop']['duration']) == ('loop_float', 1800)
        assert effect['word_highlight']['type'] == 'karaoke_wipe'
        assert effect['word_highlight']['color'] == '#4D9FFF'
        assert page.project.to_dict()['styles'][0] == before['styles'][0]
        page.undo_stack.undo(); assert [c.effect_id for c in page.project.cues] == ['none']*3
        page.undo_stack.redo(); assert page.project.effects[page.project.cues[0].effect_id] == effect
        loaded = load_project(save_project(page.project, tmp_path/'motion.2byteasr'))
        assert loaded.effects[loaded.cues[0].effect_id] == effect
    finally: close(page)


def test_blue_karaoke_interpolates_and_stops_in_gaps(app):
    p = fixture_project()
    motion_command(p, ['a','b'], words={'type': 'karaoke_wipe'}).redo()
    plan = build_word_animation(p, p.cues[0])
    first, second, last = plan['units']
    assert sample(first, 50)['ink'] == 0
    assert .4 < sample(first, 200)['ink'] < .7
    assert sample(first, 400)['ink'] == sample(first, 600)['ink'] == 1
    assert sample(second, 600)['ink'] == 0
    assert sample(last, 2800)['ink'] == 1
    fallback = build_word_animation(p, p.cues[1])
    assert not fallback['spans']
    assert all(sample(fallback['units'][0], t)['ink'] == 0 for t in (0, 500, 999))
    ass = compile_ass(p)
    assert r'\1c&HFFFFFF&' in ass and r'\1c&HFF9F4D&' in ass
    assert r'\clip(' in ass


@pytest.mark.parametrize('mode,channel', [('loop_breathe','scale'), ('loop_float','y'), ('loop_sway','x')])
def test_loop_period_window_and_export_clock(mode, channel, app, tmp_path):
    from twobyteasr.advanced_renderer import _native_segment_project
    from twobyteasr.studio_revisions import StudioRevisionStore
    p = fixture_project()
    effect = {'entry': {'type':'soft_fade','duration':200}, 'exit': {'type':'soft_fade','duration':300},
              'loop': {'type':mode,'duration':800}}
    motion_command(p, ['a'], motion=effect).redo()
    plan = build_word_animation(p, p.cues[0]); unit = plan['units'][0]
    base = 1 if channel == 'scale' else 0
    assert sample(unit, 50)[channel] == base
    assert sample(unit, 2900)[channel] == base
    assert sample(unit, 500)[channel] != base
    assert sample(unit, 500)[channel] == pytest.approx(sample(unit, 1300)[channel])
    # Continuous clock survives excerpting and the frozen revision route.
    segment = _native_segment_project(p, 1800, 3200)
    cut = segment._word_animation_plans['a']
    from twobyteasr.word_animation import remap_word_animation
    cut = remap_word_animation(cut, cut['text'])
    assert sample(cut['units'][0], 500)[channel] == pytest.approx(sample(unit, 1300)[channel])
    assert compile_ass_revision(StudioRevisionStore(p).render) == compile_ass(p)
    assert r'\move(' in compile_ass(p)
    # Long/fast loops remain analytic, without exceeding the graph's 64-key limit.
    p.cues[0].end_ms = 31000
    build_visual_cue_snapshot(p, 'a')


def test_loop_validation_is_optional_and_bounded():
    assert 'loop' not in validate_effect({'type':'none'})
    assert validate_effect({'loop': {'type':'loop_float'}})['loop']['duration'] == 1200
    with pytest.raises(EffectValidationError): validate_effect({'loop': {'type':'word_reveal'}})
    with pytest.raises(EffectValidationError): validate_effect({'loop': {'type':'loop_float','duration':0}})
    with pytest.raises(EffectValidationError): validate_effect({'loop': {'type':'loop_float','duration':100}})
