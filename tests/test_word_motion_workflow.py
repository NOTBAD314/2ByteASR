import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle, save_project, load_project
from twobyteasr.motion_application import motion_command
from twobyteasr.word_animation import build_word_animation, word_state
from twobyteasr.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.effect_dsl import builtin_effects
from twobyteasr.ass_compiler import compile_ass


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def fixture_project():
    return SubtitleProject(media=StudioMedia(path='missing.mp4', duration_ms=5000, width=640, height=360),
        styles=[SubtitleStyle('default', 'Default', font_family='Arial', font_size=60, shadow=0)],
        cues=[StudioCue('a', 1000, 4000, '你好，world!', evidence_refs=['r']),
              StudioCue('b', 4000, 5000, '没有时间')],
        asr_evidence={'r': {'words': [dict(text=t, start_ms=a, end_ms=b)
            for t,a,b in [('你', 1100, 1300), ('好', 1700, 2000), ('world', 2600, 3200)]]}})


@pytest.mark.parametrize('mode', ['word_reveal', 'karaoke_highlight', 'word_current'])
def test_measured_timing_and_punctuation(mode, app):
    p = fixture_project()
    motion_command(p, ['a'], words={'type': mode}).redo()
    plan = build_word_animation(p, p.cues[0])
    assert plan['status'] == 'measured'
    assert [r['start_ms'] for r in plan['spans']] == [100, 700, 1600]
    assert [plan['text'][r['char_start']:r['char_end']] for r in plan['spans']] == ['你', '好，', 'world!']
    assert word_state(plan, 50) == (0, 0, 0)
    assert word_state(plan, 800)[1:] == (2, 0)
    ass = compile_ass(p)
    assert r'\t(700,701,' in ass
    assert r'\kf' not in ass


def test_scope_undo_and_persistence_keep_appearance(app, tmp_path):
    p = fixture_project()
    p.cues[0].appearance_override = {'font_size': 75}
    before = p.to_dict()
    stack = QUndoStack()
    stack.push(motion_command(p, ['a'], motion=builtin_effects()['soft_pop'], words={'type': 'word_reveal'}))
    assert p.cues[1].effect_id == before['cues'][1]['effect_id']
    assert p.cues[0].appearance_override == {'font_size': 75}
    assert p.to_dict()['styles'][0] == before['styles'][0]
    path = tmp_path/'sample.2byteasr'
    path = save_project(p, path)
    loaded = load_project(path)
    assert build_word_animation(loaded, loaded.cues[0])['spans']
    stack.undo()
    assert [c.effect_id for c in p.cues] == [c['effect_id'] for c in before['cues']]
    stack.redo()
    assert p.cues[0].effect_id != 'none'


def test_missing_and_edited_words_do_not_get_fake_timing(app):
    p = fixture_project()
    motion_command(p, ['a', 'b'], words={'type': 'word_reveal'}).redo()
    assert not build_word_animation(p, p.cues[1])['spans']
    p.cues[0].text = '完全不一样'
    assert not build_word_animation(p, p.cues[0])['spans']
    assert '完全不一样' in compile_ass(p)


def test_effect_edit_is_immutable_outside_scope(app):
    p = fixture_project()
    motion_command(p, ['a', 'b'], motion=builtin_effects()['soft_fade']).redo()
    old_id = p.cues[1].effect_id
    old = copy.deepcopy(p.effects[old_id])
    effect = builtin_effects()['soft_fade']
    effect['entry']['duration'] = 600
    motion_command(p, ['a'], motion=effect).redo()
    assert p.cues[0].effect_id != old_id
    assert p.effects[old_id] == old


def test_snapshot_consumes_cue_effect_and_live_words(app):
    from twobyteasr.advanced_live_renderer import render_live_snapshot
    from twobyteasr.studio_live_canvas import compiled_scene_for_snapshot
    p = fixture_project()
    motion_command(p, ['a'], motion=builtin_effects()['float_up'], words={'type': 'word_reveal'}).redo()
    snap = build_visual_cue_snapshot(p, 'a')
    scene = compiled_scene_for_snapshot(snap)
    assert scene and scene.tracks
    assert scene.sample(0).value('group', 'y') > 0
    assert scene.sample(1000).value('group', 'y') == 0
    first = render_live_snapshot(snap, width=640, height=360, word_time_ms=50)
    mid = render_live_snapshot(snap, width=640, height=360, word_time_ms=800)
    end = render_live_snapshot(snap, width=640, height=360, word_time_ms=2400)
    assert first != mid and mid != end


def test_stop_motion_is_explicit_and_preserves_word_mode(app):
    p = fixture_project()
    motion_command(p, ['a'], motion=builtin_effects()['punch'], words={'type': 'word_current'}).redo()
    motion_command(p, ['a'], motion=builtin_effects()['none']).redo()
    snap = build_visual_cue_snapshot(p, 'a')
    assert not snap.style_recipe['visualGraph']['motionGraph']['tracks']
    assert snap.word_animation['mode'] == 'word_current'


def test_segment_and_frozen_revision_keep_acoustic_clock(app):
    from twobyteasr.advanced_renderer import _native_segment_project
    from twobyteasr.ass_compiler import compile_ass_revision
    from twobyteasr.studio_revisions import StudioRevisionStore
    p = fixture_project()
    motion_command(p, ['a'], words={'type': 'word_reveal'}).redo()
    assert compile_ass_revision(StudioRevisionStore(p).render) == compile_ass(p)
    segment = _native_segment_project(p, 2000, 3500)
    ass = compile_ass(segment)
    assert r'\t(600,601,' in ass  # world starts at 2600, excerpt starts at 2000
    assert r'\t(1600,1601,' not in ass
    assert r'{\alpha&H00&}你' in ass
    # A cut after all speech must retain the visible full line.
    later = compile_ass(_native_segment_project(p, 3300, 3500))
    assert r'\alpha&HFF&' not in later
    assert 'world!' in later


def test_advanced_excerpt_and_type_size_match_preview(app):
    from twobyteasr.style_recipe import StyleRecipe
    from twobyteasr.advanced_renderer import compile_composition_data
    p = fixture_project()
    p.style_recipes['default'] = StyleRecipe(name='Gradient', engine='remotion', colors={
        'fill': {'type':'linear-gradient','stops':[{'position':0,'color':'#FFFFFFFF'},
                                                {'position':1,'color':'#FFFF0000'}]}}).to_dict()
    motion_command(p, ['a'], words={'type':'word_current'}).redo()
    props = compile_composition_data(p, width=640, height=360, fps=30,
                                     start_seconds=2, duration_seconds=1.5)
    cue = props['cues'][0]
    assert cue['localOffsetMs'] == 1000
    assert cue['cueDurationMs'] == 3000
    assert cue['visual']['typography']['fontSize'] == pytest.approx(20)
    assert cue['visual']['wordAnimation']['spans'][2]['start_ms'] == 1600


def test_english_characters_grouped_and_short_cue(app):
    p = fixture_project()
    p.cues[0].text = 'Hi!'
    p.cues[0].end_ms = 1200
    p.asr_evidence['r']['words'] = [dict(text='H',start_ms=1010,end_ms=1080),
                                    dict(text='i',start_ms=1090,end_ms=1190)]
    motion_command(p, ['a'], motion=builtin_effects()['soft_pop'],words={'type':'word_reveal'}).redo()
    plan = build_word_animation(p,p.cues[0])
    assert len(plan['spans']) == 1
    assert (plan['spans'][0]['start_ms'], plan['spans'][0]['end_ms']) == (10,190)
    snapshot = build_visual_cue_snapshot(p,'a')
    assert max(k['timeMs'] for t in snapshot.style_recipe['visualGraph']['motionGraph']['tracks']
               for k in t['keyframes']) <= 200


def test_custom_native_preset_round_trip(app, tmp_path):
    from twobyteasr.motion_library import MotionPresetStore, MotionPreset
    store = MotionPresetStore(tmp_path)
    effect = builtin_effects()['soft_pop']
    effect['word_highlight'] = {'type':'word_reveal'}
    store.upsert(MotionPreset('my-reading','朗读',{'nativeEffect':effect},system=False))
    assert store.load_user()['my-reading'].motion['nativeEffect'] == effect


def test_split_caption_reuses_measured_interval(app):
    p = fixture_project()
    right = copy.deepcopy(p.cues[0])
    right.id, right.start_ms, right.text = 'split', 2300, 'world!'
    p.cues[0].end_ms, p.cues[0].text = 2200, '你好，'
    p.cues.append(right)
    motion_command(p, ['a','split'], words={'type':'word_reveal'}).redo()
    assert [s['start_ms'] for s in build_word_animation(p,p.cues[0])['spans']] == [100,700]
    assert [s['start_ms'] for s in build_word_animation(p,right)['spans']] == [300]
