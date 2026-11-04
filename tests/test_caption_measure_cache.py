"""Caption measurement caches survive a whole bilingual project pass.

2026-10-22 (report-eb10, 0.8.2): 2090 bilingual cues are ~4180 measured
texts. With 4096 LRU slots each preview rebuild walked them in order and
every lookup missed, so each edit re-measured the whole project.
"""
from twobyteasr.caption_style.resolved_caption_style import (
    MEASURE_CACHE_SIZE, fit_single_line, layout_caption, visible_glyph_size,
)
from twobyteasr.projects.studio_project import default_style


def test_room_for_a_ten_thousand_cue_bilingual_project():
    for cached in (layout_caption, fit_single_line, visible_glyph_size):
        assert cached.cache_info().maxsize == MEASURE_CACHE_SIZE >= 2 * 10_000


def test_second_pass_over_more_than_4096_texts_hits():
    style = default_style()
    layout_caption.cache_clear()
    texts = [f"第{i}句 line {i}" for i in range(4200)]

    def measure():
        for text in texts:
            layout_caption(text, style.font_family, style.bold, style.font_size, style.spacing,
                           1600.0, 1.0)
    measure()
    first = layout_caption.cache_info()
    measure()
    second = layout_caption.cache_info()
    assert first.misses == len(texts)
    assert second.misses == first.misses
    assert second.hits - first.hits == len(texts)
