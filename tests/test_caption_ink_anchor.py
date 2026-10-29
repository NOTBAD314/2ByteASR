"""Shared visible-ink anchoring, before renderer-specific font units."""
from copy import deepcopy
import math
import re

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style, _caption_ink_bounds
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle, parse_ass_dialogue_line
from twobyteasr.rendering.ass_compiler import compile_ass, escape_ass_text
from twobyteasr.rendering.ass_font_units import ass_font_style


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def project(text='这句字幕以句号结尾。'):
    return SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=3000, width=1920, height=1080),
        styles=[SubtitleStyle('default', 'Ink anchor', font_family='Microsoft YaHei', font_size=88,
                              position_x=900, position_y=800, outline_width=0, shadow=0)],
        cues=[StudioCue('one', 0, 3000, text)])


def test_actual_ink_is_distinct_from_terminal_advance_and_cached():
    p = project()
    first = resolve_caption_style(p.styles, p.speakers, p.cues[0], {}, 1920, 1080)
    rect = first.layout['inkBoundsPx']
    assert first.layout['anchorKind'] == 'glyph-ink'
    assert rect[2] < first.layout['lineBoxWidthPx']  # period side-bearing is not visible glyph ink
    initial = _caption_ink_bounds.cache_info()
    again = resolve_caption_style(p.styles, p.speakers, p.cues[0], {}, 1920, 1080)
    assert again.layout == first.layout
    assert _caption_ink_bounds.cache_info().hits > initial.hits
    p.cues[0].text = '这句字幕以汉字结尾中'
    other = resolve_caption_style(p.styles, p.speakers, p.cues[0], {}, 1920, 1080)
    assert other.layout['inkBoundsPx'] != rect


@pytest.mark.parametrize('rotation,expected', [(0, (930, 816)), (90, (884, 830)), (180, (870, 784))])
def test_native_offset_is_derived_in_glyph_space_then_scaled_and_rotated(rotation, expected):
    style = project().styles[0]
    style.scale_x, style.scale_y = 150, 80
    layout = {'inkBoundsPx': [10, 12, 350, 80], 'lineBoxWidthPx': 400, 'lineBoxHeightPx': 100}
    adjusted = ass_font_style(style, 1920, 1080, layout=layout, rotation=rotation)
    assert (adjusted.position_x, adjusted.position_y) == pytest.approx(expected)
    assert (style.position_x, style.position_y) == (900, 800)


def test_custom_anchor_and_rotation_keep_the_authored_ink_point():
    p = project('第一行。\n第二行！')
    p.cues[0].transform = {'_canvas_transform': True, 'position_x': 780., 'position_y': 680.,
                          'anchor_x': .25, 'anchor_y': .5, 'rotation': 18., 'scale_x': 120., 'scale_y': 90.}
    before = deepcopy(p.to_dict())
    caption = resolve_caption_style(p.styles, p.speakers, p.cues[0], {}, 1920, 1080)
    layout = caption.layout; l,t,r,b = layout['inkBoundsPx']
    # The native box's default bottom-center anchor is first moved to the
    # requested ink pivot; its own blank side bearing is then compensated.
    dx = ((.5-.25)*(r-l)+layout['lineBoxWidthPx']*.5-l-(r-l)*.5)*1.2
    dy = ((1-.5)*(b-t)+layout['lineBoxHeightPx']-b)*.9
    angle = math.radians(18)
    expected = (780+math.cos(angle)*dx-math.sin(angle)*dy, 680+math.sin(angle)*dx+math.cos(angle)*dy)
    event = next(line for line in compile_ass(p).splitlines() if line.startswith('Dialogue:'))
    actual = re.search(r'\\pos\(([-.\d]+),([-.\d]+)\)', event)
    assert tuple(map(float, actual.groups())) == pytest.approx(expected, abs=.011)
    assert r'\frz-18' in event
    assert p.to_dict() == before


def test_strokes_and_shadow_do_not_move_the_fill_ink_anchor():
    p = project('短句。')
    first = resolve_caption_style(p.styles, p.speakers, p.cues[0], {}, 1920, 1080)
    p.styles[0].outline_width = 8
    p.styles[0].shadow = 12
    second = resolve_caption_style(p.styles, p.speakers, p.cues[0], {}, 1920, 1080)
    assert first.layout['inkBoundsPx'] == second.layout['inkBoundsPx']
    a = ass_font_style(first.style, 1920, 1080, layout=first.layout)
    b = ass_font_style(second.style, 1920, 1080, layout=second.layout)
    assert (a.position_x, a.position_y) == (b.position_x, b.position_y)


def test_partial_authored_position_uses_the_same_anchor_in_every_layout():
    from twobyteasr.caption_style.visual_snapshot import _anchor as visual_anchor
    from twobyteasr.caption_style.bilingual_layout import _anchor as bilingual_anchor
    from twobyteasr.rendering.ass_compiler import _style_anchor_position
    style = project().styles[0]
    style.position_x, style.position_y = None, 730
    assert visual_anchor(style, 1920, 1080)[:2] == (960, 730)
    assert bilingual_anchor(style, 1920, 1080) == (960, 730)
    assert _style_anchor_position(style, 1920, 1080) == (960, 730)
    adapted = ass_font_style(style, 1920, 1080,
        layout={'inkBoundsPx': [0, 0, 400, 100], 'lineBoxWidthPx': 400, 'lineBoxHeightPx': 100})
    assert (adapted.position_x, adapted.position_y) == (960, 730)


def test_edge_spaces_retain_advance_and_round_trip_without_literal_escape_loss():
    text = 'First line \n second line'
    encoded = escape_ass_text(text)
    assert encoded == r'First line\h\N\hsecond line'
    event = 'Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,'+encoded
    assert parse_ass_dialogue_line(event)[-1] == text.replace('\n', ' ')
    literal = r'literal \h and \N'
    event = event[:event.rfind(',,')+2]+escape_ass_text(literal)
    assert parse_ass_dialogue_line(event)[-1] == literal


@pytest.mark.parametrize('granularity,expected_units', [('word', 3), ('character', 8)])
def test_hard_spaces_are_not_karaoke_units(granularity, expected_units):
    from twobyteasr.caption_style.effect_dsl import compile_effect_text
    encoded = escape_ass_text('one \n two hi ')
    rendered = compile_effect_text(encoded, {'entry': {'type': 'karaoke_highlight', 'granularity': granularity}},
                                   cue_duration_ms=2400)
    assert rendered.count(r'\kf') == expected_units
    assert r'\h' in rendered and r'\N' in rendered
