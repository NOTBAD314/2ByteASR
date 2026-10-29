from copy import deepcopy
from types import SimpleNamespace

from twobyteasr.caption_style.subtitle_stacking import compute_stack_layout
from twobyteasr.caption_design.theme_visual_bounds import measurement_key, measured_bounds


class Recipe:
    web_theme = {'id': 'test-decoration'}
    layout = {'lineHeightPx': 45}
    def to_dict(self): return {'webTheme': self.web_theme, 'layout': self.layout}


def resolved():
    return SimpleNamespace(recipe=Recipe(), line_count=1, measured_width=200,
        style=SimpleNamespace(font_size=40, scale_y=100, outline_width=0,
                              shadow=0, position_x=960, position_y=950, alignment=2))


def cue(name):
    return SimpleNamespace(id=name, text='主题装饰', start_ms=1000, end_ms=2500, transform={})


def test_measured_decoration_overrides_text_box_and_warns_without_contract():
    cues = [cue('a'), cue('b')]
    fallback = compute_stack_layout(cues, resolve_one=lambda _: resolved(), play_res_y=1080)
    assert any('HTML装饰未测量' in warning for warning in fallback.warnings)
    measured = compute_stack_layout(cues, resolve_one=lambda _: resolved(), play_res_y=1080,
        bounds_for=lambda *_: [620, 680, 680, 280])
    assert measured.offset_for('b') > 280
    assert not measured.warnings


def test_measurement_invalidates_when_authored_content_changes():
    c, style = cue('a'), resolved()
    key = measurement_key(c, style, 1920, 1080)
    p = SimpleNamespace(studio_state={'theme_visual_bounds': {key: {'version':1, 'bounds':[620,680,680,280]}}})
    assert measured_bounds(p, c, style, 1920, 1080)
    for field, value in [('text','修改正文'), ('start_ms',1100), ('end_ms',2700), ('transform',{'rotation':12})]:
        changed = deepcopy(c);setattr(changed, field, value)
        assert measured_bounds(p, changed, style, 1920, 1080) is None
    assert measured_bounds(p, c, style, 2560, 1440) is None
    p.render_settings={'fps':60}
    assert measured_bounds(p,c,style,1920,1080) is None
