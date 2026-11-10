import copy

import pytest

from twobyteasr.caption_style.style_recipe import background_padding
from twobyteasr.rendering.advanced_renderer import _normalized_recipe, scale_visual_for_composition


@pytest.mark.parametrize('value,expected', [
    (8, (8,8,8,8)), ([6], (6,6,6,6)), ([6,10], (6,10,6,10)),
    ([6,10,14], (6,10,14,10)), ([6,10,14,18], (6,10,14,18)),
    ((6,10,14,18), (6,10,14,18)), (0, (0,0,0,0)),
])
def test_css_order_preserves_all_sides(value, expected):
    assert background_padding(dict(padding=value)) == expected


def test_existing_axis_fields_override_shorthand_and_clamp_as_before():
    value = dict(padding=[1,2,3,4], paddingX=20, padding_x=30, paddingY=90)
    assert background_padding(value) == (80,30,80,30)
    assert background_padding({}) == (10,22,10,22)


def test_normalized_export_scales_asymmetry_without_mutating_saved_recipe():
    recipe = dict(name='padding test',engine='remotion',background=dict(enabled=True,padding=[6,10,14,18]))
    before = copy.deepcopy(recipe)
    visual = _normalized_recipe(recipe)
    assert recipe == before
    panel = visual['background']
    assert [panel[key] for key in ('paddingTop','paddingRight','paddingBottom','paddingLeft')] == [6,10,14,18]
    scaled = scale_visual_for_composition(visual, 960)
    assert [scaled['background'][key] for key in ('paddingTop','paddingRight','paddingBottom','paddingLeft')] == [3,5,7,9]
