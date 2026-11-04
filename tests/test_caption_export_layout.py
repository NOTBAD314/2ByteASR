"""The design-canvas layout survives native and advanced export boundaries."""
import copy
import json

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.caption_text_layout import line_source_ranges, wrap_caption_text
from twobyteasr.caption_style.resolved_caption_style import resolve_caption_style
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.rendering.advanced_renderer import compile_composition_data, normalized_visual_snapshot
from twobyteasr.rendering.ass_compiler import compile_ass


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def project(text, *, canvas=(1920, 1080), size=92, graph=False):
    p = SubtitleProject(
        media=StudioMedia('unused.mp4', duration_ms=4000, width=canvas[0], height=canvas[1]),
        styles=[SubtitleStyle('default', 'Layout', font_family='Microsoft YaHei', font_size=size,
                              outline_width=2, shadow=0)],
        cues=[StudioCue('caption', 0, 4000, text)],
        render_settings={'play_res_x': canvas[0], 'play_res_y': canvas[1]},
    )
    p.style_recipes['default'] = {
        'name': 'Canonical layout', 'engine': 'remotion',
        'typography': {'fontFamily': 'Microsoft YaHei', 'fontSize': size},
        'colors': {'fill': '#FFFFFFFF'},
        'motion': {'mode': 'explicit', 'entrance': {'type': 'letter_stagger', 'duration_ms': 300}},
    }
    if graph:
        from twobyteasr.caption_design.visual_design_graph import graph_from_style_recipe
        from twobyteasr.caption_style.style_recipe import StyleRecipe
        recipe = StyleRecipe.from_dict(p.style_recipes['default'])
        recipe.visual_graph = graph_from_style_recipe(recipe).to_dict()
        p.style_recipes['default'] = recipe.to_dict()
    return p


@pytest.mark.parametrize('text', [
    '这是足够长的中文句子，自动断行后必须完整保留每个字，也不能随着预览窗口变窄而重新排版。' * 2,
    'Every original word and every space must survive automatic line wrapping without being discarded. ' * 3,
    '手动第一行\n\nThe next paragraph is long enough to need additional automatic line breaks. ' * 2,
])
@pytest.mark.parametrize('graph', [False, True])
def test_display_lines_and_geometry_survive_dynamic_composition(text, graph):
    p = project(text, graph=graph)
    before = copy.deepcopy(p.to_dict())
    full = build_visual_cue_snapshot(p, 'caption', width=1920, height=1080)
    small = build_visual_cue_snapshot(p, 'caption', width=960, height=540)
    caption = full.resolved_caption
    assert caption.line_count > 1
    assert small.text == full.text == caption.text
    assert small.resolved_caption.layout == caption.layout
    receipt = caption.layout
    assert [line['text'] for line in receipt['lines']] == full.text.split('\n')
    assert receipt['lineCount'] == caption.line_count
    for line in receipt['lines']:
        assert text[line['sourceStart']:line['sourceEnd']] == line['text']
    normalized = normalized_visual_snapshot(full)
    assert normalized['layout']['captionLayout'] == receipt
    assert normalized['layout']['fitLocked'] is True
    assert normalized['layout']['maxWidthPx'] == caption.max_width
    assert normalized['layout']['lineHeightPx'] == receipt['lineHeightPx']
    for width, height in [(1920, 1080), (960, 540)]:
        cue = compile_composition_data(p, width=width, height=height, fps=30,
                                       start_seconds=0, duration_seconds=4)['cues'][0]
        assert cue['text'] == full.text
        assert cue['lineCount'] == caption.line_count
        assert cue['layout'] == receipt
        scale = 1 if graph else width/1920
        assert cue['visual']['layout']['lineHeightPx'] == pytest.approx(receipt['lineHeightPx']*scale)
        assert cue['visual']['layout']['maxWidthPx'] == pytest.approx(caption.max_width*scale)
    assert p.to_dict() == before


def test_manual_line_ranges_refer_to_original_crlf_and_unicode_separators():
    source = '甲乙\r\n\r\nABCDEF\u2028末行'
    wrapped = wrap_caption_text(source, lambda value: len(value)*10, 35)
    ranges = line_source_ranges(source, wrapped.lines)
    assert [row['breakAfter'] for row in ranges] == ['manual', 'manual', 'automatic', 'manual', 'none']
    for line, row in zip(wrapped.lines, ranges):
        assert source[row['sourceStart']:row['sourceEnd']] == line
        assert wrapped.text[row['displayStart']:row['displayEnd']] == line
    with pytest.raises(ValueError, match='omitted'):
        line_source_ranges('完整文字', ['完整'])


def test_portrait_uses_design_height_and_reports_real_overflow():
    p = project('第一行\n第二行\n第三行\n第四行', canvas=(1080, 1920), size=150)
    snapshot = build_visual_cue_snapshot(p, 'caption', width=540, height=960)
    caption = snapshot.resolved_caption
    assert caption.line_count == 4
    assert not caption.requires_split
    assert not caption.layout['overflow']
    assert caption.layout['playResY'] == 1920
    legacy = resolve_caption_style(p.styles, p.speakers, p.cues[0], p.style_recipes, 1080)
    assert legacy.requires_split  # compatibility for old width-only callers
    p.cues[0].text = '极'
    p.styles[0].font_size = 3000
    extreme = build_visual_cue_snapshot(p, 'caption').resolved_caption
    assert extreme.requires_split and extreme.layout['overflow']
    assert extreme.text == '极' and extreme.style.font_size == 3000


def test_native_ass_consumes_the_same_explicit_lines():
    p = project('原生字幕必须按公共排版结果换行，保留所有文字和手动分段。' * 3 + '\n末行')
    p.style_recipes.clear()
    caption = build_visual_cue_snapshot(p, 'caption').resolved_caption
    ass = compile_ass(p)
    event = next(line for line in ass.splitlines() if line.startswith('Dialogue:'))
    assert event.count(r'\N') == caption.line_count - 1
    assert r'\q2' in event
    assert caption.text.replace('\n', r'\N') in event


def test_emphasis_layout_has_complete_ranges_and_immutable_receipt():
    p = project('这一段加粗并强调的中文和 English mixed words 必须完整排版。' * 2)
    p.cues[0].appearance_override['text_marks'] = [{'start': 2, 'end': 20, 'bold': True, 'highlight': True}]
    snapshot = build_visual_cue_snapshot(p, 'caption')
    assert snapshot.text_marks
    receipt = snapshot.resolved_caption.layout
    assert receipt['lineCount'] == len(receipt['lines'])
    assert receipt['lineCount'] > 1
    assert all(row['widthPx'] >= 0 and row['baselinePx'] > 0 for row in receipt['lines'])
    for row in receipt['lines']:
        assert p.cues[0].text[row['sourceStart']:row['sourceEnd']] == row['text']
    receipt['lines'].clear()
    assert snapshot.resolved_caption.layout['lines']
    assert json.loads(snapshot.resolved_caption.layout_json)['font']['loaded']


def test_marked_crlf_and_blank_lines_keep_source_positions():
    p = project('加粗第一行\r\n\r\n普通末行')
    p.cues[0].appearance_override['text_marks'] = [{'start': 0, 'end': 5, 'bold': True}]
    caption = build_visual_cue_snapshot(p, 'caption').resolved_caption
    assert caption.text == '加粗第一行\n\n普通末行'
    assert caption.line_count == 3
    assert [r['text'] for r in caption.layout['lines']] == caption.text.split('\n')


def test_style_identity_is_not_fragmented_by_per_cue_layout_receipts():
    p = project('短句甲')
    first = build_visual_cue_snapshot(p, 'caption').resolved_caption
    p.cues[0].text = '短句乙'
    second = build_visual_cue_snapshot(p, 'caption').resolved_caption
    assert first.style_hash == second.style_hash
    assert first.layout_json != second.layout_json


def test_bilingual_companions_keep_separate_layouts_in_export():
    p = project('原文字幕很长，应该按画布宽度换成数行，并为下面的翻译保留空间。' * 2)
    p.studio_state['bilingual'] = {'mode': 'bilingual'}
    p.generation_metadata['translations'] = {'caption': 'This translated caption also needs measured line wrapping. ' * 3}
    from twobyteasr.caption_style.bilingual_layout import materialize_display_project
    display = materialize_display_project(p)
    payload = compile_composition_data(p, width=1920, height=1080, fps=30,
                                       start_seconds=0, duration_seconds=4)
    assert len(payload['cues']) == 2
    for row in payload['cues']:
        expected = build_visual_cue_snapshot(display, row['id']).resolved_caption
        assert row['text'] == expected.text
        assert row['layout'] == expected.layout
        assert row['lineCount'] == expected.line_count
