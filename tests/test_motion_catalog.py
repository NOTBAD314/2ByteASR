"""Curated entry/exit/loop catalog: poses, timing, three renderers, panel."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import re

import pytest

from tests.test_word_motion_workflow import app  # noqa: F401  (QApplication fixture)
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
from twobyteasr.caption_style.effect_dsl import validate_effect, builtin_effects, preset_effect, EffectValidationError
from twobyteasr.caption_style.letter_motion import sample
from twobyteasr.caption_style.motion_application import motion_command
from twobyteasr.caption_style.motion_catalog import (ENTRY, EXIT, LOOP, CATEGORIES, RICH_ENTRY, RICH_EXIT,
                                                     RICH_LOOP, entry_pose, exit_pose, Ctx, wipe_bands, signature_progress)
from twobyteasr.caption_style.word_animation import build_word_animation, needs_word_plan
from twobyteasr.rendering.ass_compiler import compile_ass

TEXT = '这波操作 Nice'
DURATION = 4000


def project(effect, *, words=True, text=TEXT, duration=DURATION):
    p = SubtitleProject(media=StudioMedia(path='x.mp4', duration_ms=duration, width=960, height=540),
        styles=[SubtitleStyle('default', 's', font_family='Microsoft YaHei', font_size=72)],
        cues=[StudioCue('c', 0, duration, text, effect_id='e', evidence_refs=['c'])],
        asr_evidence={'c': {'words': [dict(text=t, start_ms=300+i*260, end_ms=520+i*260)
                                      for i, t in enumerate(text.replace(' ', ''))]}} if words else {})
    p.effects['e'] = validate_effect(effect)
    return p


def one(stage, key, **extra):
    effect = {'entry': {'type': 'none'}, 'exit': {'type': 'none'}}
    if stage == 'loop':
        effect['loop'] = {'type': key, **extra}
    else:
        effect[stage] = {'type': key, **extra}
    return effect


def visible_units(plan):
    return [u for u in plan['units'] if plan['text'][u['char_start']:u['char_end']].strip()]


def shown(state):
    bands = wipe_bands(state['cut'], state['reveal'])
    return state['opacity'] > .01 and (bands is None or bands != [])


REST = {'opacity': 1., 'x': 0., 'y': 0., 'scale': 1., 'rotation': 0., 'blur': 0., 'sx': 1., 'sy': 1., 'skew': 0.,
        'flash': 0., 'ghost': 0., 'rgb': 0., 'slice': 0., 'strips': 0., 'door': 0., 'cut': 0., 'caret': 0., 'halo': 0.}


def test_catalog_is_complete_and_named_once():
    for stage, items in (('entry', ENTRY), ('exit', EXIT), ('loop', LOOP)):
        keys = [m.key for m in items]
        assert len(keys) == len(set(keys))
        assert len({m.label for m in items}) == len(items)
        assert {m.category for m in items} <= {c for c, _ in CATEGORIES[stage]}
    assert len(ENTRY) >= 28 and len(EXIT) >= 17 and len(LOOP) >= 13
    ctx = Ctx(k=1., fx=-1., fy=0., b=1., w=4., seed=2)
    for key in RICH_ENTRY:
        assert entry_pose(key, .3, ctx), key
    for key in RICH_EXIT:
        assert exit_pose(key, .3, ctx), key
    assert not (RICH_ENTRY & RICH_EXIT)


def test_curated_presets_never_seed_project_files():
    # Every new project stores builtin_effects(); older builds must still open it.
    assert not (RICH_ENTRY | RICH_EXIT) & set(builtin_effects())
    assert preset_effect('push_in')['entry']['type'] == 'push_in'
    assert preset_effect('soft_pop') == builtin_effects()['soft_pop']
    assert 'push_in' not in SubtitleProject(media=StudioMedia(path='x.mp4', duration_ms=10)).effects


@pytest.mark.parametrize('key', sorted(RICH_ENTRY))
def test_entry_starts_hidden_and_settles_exactly(key):
    plan = build_word_animation(project(one('entry', key)), project(one('entry', key)).cues[0])
    units = visible_units(plan)
    assert units
    assert not any(shown(sample(u, 0)) for u in units), key
    for u in units:
        state = sample(u, DURATION/2)
        for name, value in REST.items():
            assert state[name] == pytest.approx(value, abs=1e-3), (key, name)
        assert state['reveal'] >= 1 and not -.6 < state['shine'] < 1.6


@pytest.mark.parametrize('key', sorted(RICH_EXIT))
def test_exit_leaves_nothing_and_rests_before(key):
    p = project(one('exit', key))
    units = visible_units(build_word_animation(p, p.cues[0]))
    for u in units:
        state = sample(u, DURATION/2)
        for name, value in REST.items():
            assert state[name] == pytest.approx(value, abs=1e-3), (key, name)
    assert not any(shown(sample(u, DURATION)) for u in units), key


def test_per_glyph_entries_stagger_without_inventing_speech():
    p = project(one('entry', 'char_rise'), words=False)
    plan = build_word_animation(p, p.cues[0])
    assert plan['spans'] == [] and plan['status'] != 'measured'
    units = visible_units(plan)
    assert len(units) == len(TEXT.replace(' ', ''))
    first = next(f[0] for f in units[0]['frames'] if f[1] > 0)
    last = next(f[0] for f in units[-1]['frames'] if f[1] > 0)
    assert first < last <= 800
    # With a word mode the measured word units are kept, untouched.
    effect = {**one('entry', 'char_rise'), 'word_highlight': {'type': 'karaoke_wipe'}}
    p = project(effect)
    plan = build_word_animation(p, p.cues[0])
    assert len(plan['units']) == len(plan['spans'])
    assert [s['start_ms'] for s in plan['spans']] == [300+260*i for i in range(len(plan['spans']))]


def test_seek_is_deterministic_and_excerpts_keep_the_clock():
    from twobyteasr.rendering.advanced_renderer import _native_segment_project
    from twobyteasr.caption_style.word_animation import remap_word_animation
    p = project({**one('entry', 'glitch_in'), 'exit': {'type': 'char_drop_out'}, 'loop': {'type': 'loop_shake'}})
    plan = build_word_animation(p, p.cues[0])
    unit = plan['units'][0]
    forward = [sample(unit, t) for t in range(0, DURATION, 97)]
    backward = [sample(unit, t) for t in reversed(range(0, DURATION, 97))][::-1]
    assert forward == backward
    segment = _native_segment_project(p, 1500, 4000)
    cut = remap_word_animation(segment._word_animation_plans['c'], TEXT)
    for t in (100, 900, 2300):
        assert sample(cut['units'][0], t) == pytest.approx(sample(unit, t+1500))


@pytest.mark.parametrize('key', sorted(RICH_ENTRY | RICH_EXIT | RICH_LOOP))
def test_every_curated_preset_compiles_to_ass(key, app):
    stage = 'entry' if key in RICH_ENTRY else 'exit' if key in RICH_EXIT else 'loop'
    p = project(one(stage, key))
    assert needs_word_plan(p.effects['e'])
    ass = compile_ass(p)
    events = [line for line in ass.splitlines() if line.startswith('Dialogue:')]
    assert len(events) > 3, key
    layers = {int(line.split(':', 1)[1].split(',', 1)[0]) for line in events}
    assert layers <= {0, 1, 2} and 1 in layers, key


def test_ass_layers_trails_under_and_flash_over(app):
    ass = compile_ass(project(one('entry', 'push_in')))
    back = [l for l in ass.splitlines() if l.startswith('Dialogue: 0,')]
    assert back and all('\\alpha&H' in l for l in back)
    ass = compile_ass(project(one('entry', 'flash_in')))
    assert re.search(r'Dialogue: 2,.*\\1c&HFFFFFF&', ass)
    assert '\\fax' in compile_ass(project(one('entry', 'whip_in')))
    assert '\\clip(m' in compile_ass(project(one('entry', 'wipe_in')))


def test_direction_and_stagger_validate():
    effect = validate_effect({'entry': {'type': 'push_in', 'direction': 'up'}, 'exit': {'type': 'slide_out'}})
    assert effect['entry']['direction'] == 'up' and effect['exit']['direction'] == 'right'
    assert validate_effect({'entry': {'type': 'char_rise', 'stagger': 40}})['entry']['stagger'] == 40
    with pytest.raises(EffectValidationError):
        validate_effect({'entry': {'type': 'push_in', 'direction': 'diagonal'}})
    up = build_word_animation(project({'entry': {'type': 'push_in', 'direction': 'up'}, 'exit': {'type': 'none'}}),
                              project({'entry': {'type': 'push_in', 'direction': 'up'}, 'exit': {'type': 'none'}}).cues[0])
    state = sample(up['units'][0], 30)
    assert state['y'] < -.3 and abs(state['x']) < 1e-6


def test_posters_catch_motion_not_the_settled_line():
    for m in ENTRY+EXIT:
        if m.legacy:
            continue
        u = signature_progress(m.stage, m.key)
        assert .05 <= u <= .95
    ctx = Ctx(k=1., fx=-1., fy=0., b=1., w=4., seed=2)
    assert entry_pose('push_in', signature_progress('entry', 'push_in'), ctx)['ghost'] > .15


def test_panel_cards_filters_direction_and_web_theme(tmp_path):
    from tests.test_motion_workflow_ui import make_page, close
    _, page = make_page(tmp_path)
    try:
        inspector = page.motion_inspector
        for stage, items in (('entry', ENTRY), ('exit', EXIT), ('loop', LOOP)):
            assert all((stage, m.key) in inspector.cards for m in items)
        inspector.tabs.setCurrentIndex(0)
        inspector.filter('entry', 'cinema')
        assert all(not tile.isVisibleTo(inspector) or m == 'cinema'
                   for (s, k), tile in inspector.cards.items() if s == 'entry'
                   for m in [next(i.category for i in ENTRY if i.key == k)])
        inspector.choose('entry', 'push_in')
        inspector.set_direction('up')
        inspector.choose('exit', 'char_drop_out')
        assert page.effect_out_duration.value() == 760
        effect = page._motion_workflow.motion_effect() if hasattr(page, '_motion_workflow') else None
        effect = effect or inspector.workflow.motion_effect()
        assert (effect['entry']['type'], effect['entry']['direction'], effect['exit']['type']) == ('push_in', 'up', 'char_drop_out')
        assert inspector.tabs.buttons[0].value_text == '冲刺推入'
        before = dict(page.project.effects)
        assert page.project.effects == before
        page.motion_apply.click()
        applied = page.project.effects[page.project.cues[0].effect_id]
        assert applied['entry']['direction'] == 'up'
        # A web-theme cue keeps its own animation but the page still previews.
        cue = page.project.cues[0]
        page.project.style_recipes[cue.style_id] = {**page.project.style_recipes.get(cue.style_id, {}),
                                                    'webTheme': {'cueHtml': '<b>{{words}}</b>'}}
        inspector.workflow.preview()
        assert page.motion_sample.snapshot is not None and page.motion_sample.snapshot.text == '示例字幕'
        inspector.workflow.update_status()
        assert '网页主题' in page.motion_status.text() and not page.motion_apply.isEnabled()
    finally:
        close(page)
