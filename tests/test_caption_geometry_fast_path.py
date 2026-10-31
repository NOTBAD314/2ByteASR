"""Numeric geometry must match measured bilingual geometry without glyph work."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia
from twobyteasr.caption_style.caption_layer_transform import displayed_layer, resolved_values, layer_values


def reference(project, cue, language):
    from twobyteasr.caption_style.style_resolution import resolve_cue_visual
    from twobyteasr.caption_style.visual_snapshot import _anchor
    shown = displayed_layer(project, cue, language)
    if shown is None:
        return None
    style = resolve_cue_visual(project, shown).style
    x, y, ax, ay = _anchor(style, 1920, 1080)
    return dict(position_x=x, position_y=y, scale_x=style.scale_x, scale_y=style.scale_y,
        rotation=float(shown.transform.get('rotation', 0)),
        anchor_x=float(shown.transform.get('anchor_x', ax)), anchor_y=float(shown.transform.get('anchor_y', ay)),
        font_size=style.font_size, scale_link=bool(layer_values(cue, language).get('scale_link', True)))


@pytest.mark.parametrize('alignment', range(1, 10))
@pytest.mark.parametrize('order', ['translation_first', 'original_first'])
@pytest.mark.parametrize('custom', [False, True])
def test_fast_values_equal_existing_measured_layout(alignment, order, custom):
    app = QApplication.instance() or QApplication([])
    cue = StudioCue('c', 1000, 4000, 'Una frase italiana abbastanza lunga, con più parole!')
    cue.transform = {'initial_layout': {'position_x': 739., 'position_y': 945.,
                                      'play_res_x': 1920, 'play_res_y': 1080}}
    if custom:
        cue.transform.update(language_layers={'original': {'position_x': 810., 'scale_x': 125.,
                             'anchor_x': .2, 'rotation': 8., 'font_size': 63., 'scale_link': False}})
        cue.appearance_override = {'original': {'font_size': 47.}}
    project = SubtitleProject(media=StudioMedia(''), cues=[cue],
        generation_metadata={'translations': {'c': '这条中文译文也保留完整换行与字形几何'}},
        studio_state={'bilingual': {'mode': 'bilingual', 'order': order, 'layout': 'ink_v1'}})
    project.styles[0].alignment = alignment
    before = deepcopy(cue)
    assert resolved_values(project, cue, 'original', geometry_only=True) == reference(project, cue, 'original')
    assert cue == before


def test_anchored_original_does_not_measure_unrelated_text(monkeypatch):
    app = QApplication.instance() or QApplication([])
    cue = StudioCue('c', 0, 1000, 'Come cambia una lunga frase')
    project = SubtitleProject(media=StudioMedia(''), cues=[cue],
        generation_metadata={'translations': {'c': '原文在下方'}},
        studio_state={'bilingual': {'mode': 'bilingual', 'order': 'translation_first', 'layout': 'ink_v1'}})
    expected = reference(project, cue, 'original')
    def no_glyphs(*args, **kwargs):
        raise AssertionError('Anchored geometry must not shape text')
    monkeypatch.setattr('twobyteasr.caption_style.resolved_caption_style.resolve_caption_style', no_glyphs)
    assert resolved_values(project, cue, 'original', geometry_only=True) == expected


def test_group_transform_keeps_measured_path():
    app = QApplication.instance() or QApplication([])
    cue = StudioCue('c', 0, 1000, 'Originale')
    project = SubtitleProject(media=StudioMedia(''), cues=[cue],
        generation_metadata={'translations': {'c': '完整译文'}},
        studio_state={'bilingual': {'mode': 'bilingual'},
                      'caption_group_transform': {'version': 1, 'defaults': {'original': {'scale_x': 120.}}}})
    assert resolved_values(project, cue, 'original', geometry_only=True) == reference(project, cue, 'original')
