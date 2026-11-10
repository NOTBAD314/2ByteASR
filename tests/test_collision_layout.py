"""Actual renderer pixels and baseline ownership for active-set collision layout."""
from copy import deepcopy
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, SubtitleStyle, save_project, load_project
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_style.collision_layout import solve_layout, layout_schedule, shifted_snapshot, visual_bounds
from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
from twobyteasr.studio.selection_geometry import image_bounds


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project(count=2):
    return SubtitleProject(media=StudioMedia('missing.mp4', duration_ms=6000),
        speakers=[StudioSpeaker(f'S{i}') for i in range(count)],
        styles=[SubtitleStyle('default', 'Default', font_size=120, outline_width=16,
            shadow=0, margin_v=65)],
        cues=[StudioCue(chr(97+i), i*100, 4000+i*100, '那就再刷一下吧', speaker_id=f'S{i}') for i in range(count)])


def snapshots(p):
    return [build_visual_cue_snapshot(p, c.id) for c in p.cues]


def pixel_bounds(s):
    return image_bounds(render_live_snapshot(s, width=s.playres_x, height=s.playres_y))


def test_thick_strokes_have_real_visible_gap_and_do_not_edit_project():
    p = project()
    p.cues[1].appearance_override = {'outline_color': '#FFFF7900'}
    before = deepcopy(p.to_dict())
    ss = snapshots(p)
    layout = solve_layout(ss)
    lower = pixel_bounds(shifted_snapshot(ss[0], layout.offsets['a']))
    upper = pixel_bounds(shifted_snapshot(ss[1], layout.offsets['b']))
    assert 6 <= lower[1] - (upper[1]+upper[3]) <= 12
    assert not layout.warnings
    assert p.to_dict() == before


@pytest.mark.parametrize('count', [2, 3, 4])
def test_delete_each_peer_resolves_from_baseline_without_drift(count):
    p = project(count)
    ss = snapshots(p)
    for removed in range(count):
        remaining = ss[:removed]+ss[removed+1:]
        first = solve_layout(remaining)
        assert solve_layout(reversed(remaining)) == first
        if len(remaining) == 1:
            assert list(first.offsets.values()) == [0]
        for _ in range(10):
            solve_layout(ss)  # undo
            assert solve_layout(remaining) == first  # redo
        boxes = [visual_bounds(s).translated(0, -first.offsets[s.cue_id]) for s in remaining]
        for i, box in enumerate(boxes):
            assert all(not box.intersects(other) for other in boxes[:i])


def test_manual_position_returns_to_manual_base_and_old_auto_anchor_is_recovered(tmp_path):
    p = project()
    p.cues[0].transform = {'initial_layout': {'version': 1, 'source': 'temporal_overlap',
        'position_x': 960, 'position_y': 700, 'offset_y': 315}}
    p.cues[1].transform = {'position_x': 950, 'position_y': 930}
    ss = snapshots(p)
    assert ss[0].position_y == 1015
    assert ss[1].position_y == 930
    assert solve_layout([ss[1]]).offsets['b'] == 0
    save_project(p, tmp_path/'saved.2byteproj')
    assert solve_layout(snapshots(load_project(tmp_path/'saved.2byteproj'))) == solve_layout(ss)
    assert p.cues[1].transform == {'position_x': 950, 'position_y': 930}


def test_horizontal_separation_and_scaling():
    p = project()
    p.cues[0].text = p.cues[1].text = '短字'
    p.cues[0].transform = {'position_x': 300, 'position_y': 900}
    p.cues[1].transform = {'position_x': 1500, 'position_y': 900}
    ss = snapshots(p)
    assert all(v == 0 for v in solve_layout(ss).offsets.values())
    assert solve_layout([replace(s, resolution=(960, 540)) for s in ss]) == solve_layout(ss)


def test_multiline_background_shadow_glow_and_rotated_scaled_envelope():
    p = project()
    p.cues[1].text = '上面一行\n下面一行'
    p.cues[1].transform = {'scale_x': 115, 'scale_y': 120, 'rotation': 8}
    p.styles[0].border_style = 3
    p.styles[0].shadow = 8
    ss = snapshots(p)
    ss[1] = replace(ss[1], glow={'enabled': True, 'radius': 8, 'spread': 3})
    layout = solve_layout(ss)
    boxes = [pixel_bounds(shifted_snapshot(s, layout.offsets[s.cue_id])) for s in ss]
    # A barely visible shadow halo is not the caption's collision edge.
    from PIL import Image
    from PySide6.QtGui import QImage
    visible = []
    for s in ss:
        image = render_live_snapshot(shifted_snapshot(s, layout.offsets[s.cue_id]), width=1920, height=1080)
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        alpha = Image.frombytes('RGBA', (image.width(),image.height()), bytes(image.constBits()),
            'raw','RGBA',image.bytesPerLine()).getchannel('A')
        visible.append(alpha.point(lambda value: 255 if value >= 8 else 0).getbbox())
    assert visible[0][1]-visible[1][3] >= 6


def test_timing_boundary_schedule_and_seek_are_identical():
    ss = snapshots(project())
    schedule = layout_schedule(ss)
    for at in [0, 100, 3999, 4000, 4099]:
        active = [s for s in ss if s.start_ms <= at < s.end_ms]
        expected = {s.cue_id: solve_layout(ss).offsets[s.cue_id] for s in active}
        assert {s.cue_id: next(o for a, b, o in schedule[s.cue_id] if a <= at < b) for s in active} == expected
    assert len(schedule['b']) == 1 and schedule['b'][0][2] > 0


def test_no_room_is_explicit_and_does_not_push_caption_offscreen():
    ss = snapshots(project(12))
    layout = solve_layout(ss)
    assert layout.warnings
    for s in ss:
        assert visual_bounds(s).top()-layout.offsets[s.cue_id] >= 0


def test_disabled_layout_is_empty():
    assert solve_layout(snapshots(project()), enabled=False).offsets == {}


def test_ass_layout_retains_original_animation_clock_and_moves_vector_clip():
    from twobyteasr.rendering.ass_collision_layout import apply_layout_events
    lines = ['; CollisionCue=a',
        r'Dialogue: 0,0:00:00.00,0:00:04.00,Default,S0,0,0,0,,{\pos(960,1000)\fad(200,300)\t(0,300,\fscx110)}文字']
    result = list(apply_layout_events(lines, {'a':[(0,2000,150),(2000,4000,0)]},1920,1080))
    assert len(result) == 3
    assert all('0:00:00.00,0:00:04.00' in row for row in result[1:])
    assert all(r'\fad(200,300)\t(0,300,\fscx110)' in row for row in result[1:])
    assert r'\pos(960,850.000)' in result[1]
    lines = ['; CollisionCue=a',
        r'Dialogue: 0,0:00:00.00,0:00:01.00,Default,S0,0,0,0,,{\pos(960,1000)\clip(m 500 900 l 700 900 700 1000 500 1000)\alpha&H80&}字']
    result = list(apply_layout_events(lines,{'a':[(0,500,100),(500,1000,0)]},1920,1080))
    assert r'\clip(m 500 800.000 l 700 800.000 700 900.000 500 900.000)' in result[1]
    assert r'\alpha&H80&' in result[1] and r'\fade(' in result[1]


def test_bilingual_companion_moves_with_parent():
    ss = snapshots(project())
    companion = replace(ss[1], cue_id='b#tr', position_y=ss[1].position_y-170, font_size=70.)
    result = solve_layout([*ss,companion])
    assert result.offsets['b#tr'] == result.offsets['b']


def test_subtitle_eye_filters_export_and_audio_mute_does_not():
    from twobyteasr.caption_style.collision_layout import project_layout_schedule
    from twobyteasr.rendering.ass_compiler import compile_ass
    p = project()
    p.cues[0].text = '隐藏行'
    p.cues[1].text = '保留行'
    p.studio_state['muted_speakers'] = ['S0']
    assert set(project_layout_schedule(p)) == {'a','b'}
    p.studio_state['subtitle_track_visibility'] = {'S0': False}
    assert project_layout_schedule(p) == {'b': [(100,4100,0.)]}
    ass = compile_ass(p)
    assert '隐藏行' not in ass and '保留行' in ass


def test_advanced_export_spans_keep_baseline_and_original_motion_clock():
    from twobyteasr.rendering.advanced_renderer import compile_composition_data
    from twobyteasr.caption_style.collision_layout import project_layout_schedule
    p = project()
    p.style_recipes['default'] = {'name':'Static','engine':'remotion','motion':{'mode':'none'}}
    original = deepcopy(p.to_dict())
    schedule = project_layout_schedule(p)
    props = compile_composition_data(p,width=960,height=540,fps=30,start_seconds=1,duration_seconds=4)
    rows = [row for row in props['cues'] if row['sourceId']=='b']
    assert len(rows) == 1
    assert rows[0]['localOffsetMs'] == 900
    assert all(row['cueDurationMs'] == 4000 for row in rows)
    assert rows[0]['layoutOffsetY'] == schedule['b'][0][2]
    p.studio_state['subtitle_track_visibility'] = {'S0':False}
    before = deepcopy(p.to_dict())
    props = compile_composition_data(p,width=1920,height=1080,fps=30,start_seconds=0,duration_seconds=5)
    assert [r['sourceId'] for r in props['cues']] == ['b']
    assert p.to_dict() == before
    p.studio_state.pop('subtitle_track_visibility')
    assert p.to_dict() == original


def test_empty_unpainted_caption_does_not_reserve_space():
    ss = snapshots(project())
    blank = replace(ss[0],text='  ',shadow={},glow={},style_recipe={})
    assert solve_layout([blank,ss[1]]).offsets.get('b',0) == 0
