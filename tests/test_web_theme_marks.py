"""A caption's own marks (Markdown / AI 生动标记) inside an AI web theme."""
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_design.caption_components import compose
from twobyteasr.caption_design.web_theme import _LIVE_DRIVER_SCRIPT, substitute_placeholders
from twobyteasr.caption_design.web_theme_marks import SEPARATOR, marked_text, split_marked, theme_marks
from twobyteasr.caption_style.style_recipe import StyleRecipe
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot, web_theme_text
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle

ROOT = Path(__file__).resolve().parents[1]
TEXT = '这一波操作直接把我看傻了'
MARKS = [dict(start=3, end=5, bold=True), dict(start=5, end=7, strike=True),
         dict(start=7, end=9, color='#00C2FF', italic=True), dict(start=9, end=12, highlight=True)]


@pytest.fixture(scope='module', autouse=True)
def application():
    yield QApplication.instance() or QApplication([])


def project(marks=None, *, web=True):
    p = SubtitleProject(media=StudioMedia('unused.mp4', duration_ms=4000, width=1920, height=1080),
                        styles=[SubtitleStyle('default', 'S', font_family='Microsoft YaHei', font_size=60)],
                        cues=[StudioCue('c', 0, 4000, TEXT)], render_settings={'play_res_x': 1920, 'play_res_y': 1080})
    theme = dict(name='kit', **compose(dict(version=11, kit='glass')))
    p.style_recipes['default'] = (StyleRecipe(name='Web', engine='remotion', web_theme=theme).to_dict() if web else
                                  {'name': 'Plain', 'typography': {'fontFamily': 'Microsoft YaHei', 'fontSize': 60}})
    if marks is not None:
        p.cues[0].appearance_override['text_marks'] = marks
    return p


def test_marks_resolve_to_theme_classes_on_the_displayed_text():
    rows = theme_marks(TEXT, MARKS + [dict(start=0, end=2, heading=2), dict(start=0, end=1, bold=False)])
    assert rows == [[0, 2, 'wt-h2', '', ''], [3, 5, 'wt-b', '', ''], [5, 7, 'wt-s', '', ''],
                    [7, 9, 'wt-i', '#00C2FF', ''], [9, 12, 'wt-hl', '', '']]
    # Colour and font come from project data: only plain values reach an inline style.
    unsafe = theme_marks(TEXT, [dict(start=0, end=2, color='red;background:url(x)'), dict(start=2, end=4, font='A";}*{color:red'),
                                dict(start=4, end=6, font='霞鹜文楷 Bold', color='#aBc123')])
    assert unsafe == [[4, 6, '', '#aBc123', '霞鹜文楷 Bold']]
    assert theme_marks(TEXT, []) == [] and theme_marks(TEXT, None) == []


def test_marks_ride_with_the_text_and_an_unmarked_line_is_untouched():
    rows = theme_marks(TEXT, MARKS)
    carried = marked_text(TEXT, rows)
    assert carried.startswith(TEXT + SEPARATOR) and split_marked(carried) == (TEXT, carried.split(SEPARATOR, 1)[1])
    assert json.loads(split_marked(carried)[1]) == rows
    assert marked_text(TEXT, []) == TEXT and split_marked(TEXT) == (TEXT, '')
    # A broken suffix is dropped; it can never become visible characters.
    assert split_marked(TEXT + SEPARATOR + '[[1,2') == (TEXT, '') and split_marked(TEXT + SEPARATOR + '[]') == (TEXT, '')


@pytest.mark.parametrize('placeholder', ['{{text}}', '{{words}}'])
def test_expansion_keeps_every_character_and_only_adds_an_attribute(placeholder):
    template = f'<div class="line">{placeholder}</div>'
    plain = substitute_placeholders(template, text=TEXT)
    marked = substitute_placeholders(template, text=marked_text(TEXT, theme_marks(TEXT, MARKS)))
    visible = lambda markup: re.sub(r'<[^>]+>', '', markup)
    assert visible(marked) == visible(plain) == TEXT
    assert SEPARATOR not in marked and 'data-cue-marks' not in plain
    attribute = re.search(r'data-cue-marks="([^"]*)"', marked).group(1)
    assert json.loads(attribute.replace('&quot;', '"').replace('&amp;', '&')) == theme_marks(TEXT, MARKS)
    assert re.sub(r' data-cue-marks="[^"]*"', '', marked) == plain


def test_web_theme_snapshot_carries_the_caption_s_own_marks():
    snapshot = build_visual_cue_snapshot(project(MARKS), 'c', width=1920, height=1080)
    # The ordinary glyph renderers still see nothing for a web theme.
    assert snapshot.text_marks == [] and snapshot.text == TEXT
    assert snapshot.theme_marks == theme_marks(TEXT, MARKS)
    assert split_marked(web_theme_text(snapshot)) == (TEXT, json.dumps(theme_marks(TEXT, MARKS), ensure_ascii=False, separators=(',', ':')))
    ordinary = build_visual_cue_snapshot(project(MARKS, web=False), 'c', width=1920, height=1080)
    assert ordinary.theme_marks is None and ordinary.text_marks and web_theme_text(ordinary) == TEXT


def test_glossary_auto_highlights_stay_out_of_an_ai_theme():
    marks = [dict(start=0, end=3, highlight=True, source='glossary'), dict(start=9, end=12, bold=True)]
    snapshot = build_visual_cue_snapshot(project(marks), 'c', width=1920, height=1080)
    assert snapshot.theme_marks == [[9, 12, 'wt-b', '', '']]


def test_marks_change_every_identity_and_their_absence_changes_none():
    bare = build_visual_cue_snapshot(project(), 'c', width=1920, height=1080)
    marked = build_visual_cue_snapshot(project(MARKS), 'c', width=1920, height=1080)
    assert bare.theme_marks is None and web_theme_text(bare) == TEXT
    # Unmarked captions hash exactly as they did before the field existed.
    assert 'theme_marks' not in json.dumps({k: v for k, v in bare.to_dict().items() if v}, default=str)
    assert replace(bare, theme_marks=[]).stable_hash() == bare.stable_hash()
    assert replace(bare, theme_marks=[]).pixel_hash() == bare.pixel_hash()
    assert replace(bare, theme_marks=[]).glyph_hash() == bare.glyph_hash()
    for name in ('stable_hash', 'pixel_hash', 'glyph_hash'):
        assert getattr(marked, name)() != getattr(replace(marked, theme_marks=None), name)()
    from twobyteasr.rendering.live_web_preview import prepare_web_configuration
    theme = bare.style_recipe['webTheme']
    assert (prepare_web_configuration(theme, web_theme_text(marked), duration_seconds=4).strip_key
            != prepare_web_configuration(theme, web_theme_text(bare), duration_seconds=4).strip_key)


def test_export_rows_send_marked_text_only_for_marked_web_cues():
    from twobyteasr.rendering.advanced_renderer import compile_composition_data
    row = lambda p: compile_composition_data(p, width=1920, height=1080, fps=30, start_seconds=0, duration_seconds=4)['cues'][0]
    assert row(project())['text'] == TEXT
    assert split_marked(row(project(MARKS))['text'])[0] == TEXT and SEPARATOR in row(project(MARKS))['text']


def test_all_three_expansions_and_the_shared_runtime_agree():
    tsx = (ROOT / 'renderer/src/components/WebThemeSubtitle.tsx').read_text('utf8')
    clock = (ROOT / 'renderer/src/webThemeClock.js').read_text('utf8')
    for source in (tsx, _LIVE_DRIVER_SCRIPT):
        assert 'data-cue-marks' in source and 'u0001' in source
    assert "querySelectorAll('[data-caption-text][data-cue-marks]')" in clock
    assert 'prepareEmphasis(root);\n    prepareMarks(root);'.replace('\n', '\r\n') in clock or 'prepareEmphasis(root);\n    prepareMarks(root);' in clock
    # The runtime only moves existing nodes: it creates wrappers and single-character text nodes.
    body = clock[clock.index('function prepareMarks'):clock.index('function prepareCaptionPunctuation')]
    assert 'createTextNode(char)' in body and 'innerHTML' not in body and 'textContent=' not in body.replace('style.textContent=', '')
    for name in ('wt-b', 'wt-i', 'wt-hl', 'wt-s', 'wt-h1', 'wt-h6'):
        assert f"'{name}'" in clock
