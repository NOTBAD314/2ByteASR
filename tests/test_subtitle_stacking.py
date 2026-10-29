"""Deterministic overlap stacking tests (2026-09-19 抢话自动分层)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.caption_style.subtitle_stacking import StackLayout, compute_stack_layout


class FakeResolved:
    """Minimal ResolvedCaptionStyle stand-in: 1 line, 40px line height."""

    def __init__(self, size=32.0, lines=1):
        style = SimpleNamespace(
            font_size=size, scale_y=100.0, outline_width=2.0, outline2_width=0.0,
            shadow=0.0,
        )
        recipe = SimpleNamespace(
            layout={"lineCount": lines, "lineHeightPx": 46.0},
        )
        self._style = style
        self._recipe = recipe

    @property
    def style(self):
        return self._style

    @property
    def recipe(self):
        return self._recipe

    @property
    def line_count(self):
        return self._recipe.layout["lineCount"]


def cue(cid, start, end):
    return SimpleNamespace(id=cid, start_ms=start, end_ms=end)


def test_two_overlapping_cues_stack_by_start():
    a, b = cue("A", 10_000, 12_000), cue("B", 11_000, 13_000)
    layout = compute_stack_layout(
        [b, a],  # input order irrelevant
        resolve_one=lambda c: FakeResolved(),
        play_res_y=1080,
    )
    assert layout.offset_for("A") == 0.0, "earlier cue stays lowest"
    assert layout.offset_for("B") > 40.0, "later cue lifts above A's height"
    assert layout.offset_for("B") < 120.0


def test_order_swaps_with_start_order():
    # B speaks first now: B stays lowest, A lifts.
    a, b = cue("A", 11_000, 13_000), cue("B", 10_000, 12_000)
    layout = compute_stack_layout(
        [a, b],
        resolve_one=lambda c: FakeResolved(),
        play_res_y=1080,
    )
    assert layout.offset_for("B") == 0.0
    assert layout.offset_for("A") > 40.0


def test_sequential_cues_do_not_move():
    a, b = cue("A", 10_000, 12_000), cue("B", 12_000, 14_000)
    layout = compute_stack_layout([a, b], resolve_one=lambda c: FakeResolved(), play_res_y=1080)
    assert layout.offsets == {}


def test_even_one_frame_overlap_is_readable():
    a, b = cue("A", 10_000, 12_000), cue("B", 11_960, 14_000)  # 40ms overlap
    layout = compute_stack_layout([a, b], resolve_one=lambda c: FakeResolved(), play_res_y=1080)
    assert layout.offset_for('B') > 0


def test_native_worker_frozen_revision_supports_overlap():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.rendering.ass_compiler import compile_ass_revision
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia('sample.mp4',duration_ms=3000),cues=[
        StudioCue('a',0,2000,'earlier'),StudioCue('b',1000,3000,'later')])
    result=compile_ass_revision(StudioRevisionStore(p).render)
    assert 'earlier' in result and 'later' in result
    assert '\\pos(' in result


def test_three_way_stack_is_monotonic():
    a, b, c = cue("A", 10_000, 13_000), cue("B", 11_000, 14_000), cue("C", 12_000, 15_000)
    layout = compute_stack_layout([c, a, b], resolve_one=lambda c_: FakeResolved(), play_res_y=1080)
    oa, ob, oc = layout.offset_for("A"), layout.offset_for("B"), layout.offset_for("C")
    assert oa == 0.0
    assert ob > oa
    assert oc > ob


def test_determinism_and_signature():
    a, b = cue("A", 10_000, 12_000), cue("B", 11_000, 13_000)
    r = lambda c: FakeResolved(size=48.0, lines=2)
    first = compute_stack_layout([a, b], resolve_one=r, play_res_y=1080)
    second = compute_stack_layout([b, a], resolve_one=r, play_res_y=1080)
    assert first.offsets == second.offsets
    assert "B:" in first.signature


def test_multiline_and_scale_raise_height():
    a, b = cue("A", 10_000, 12_000), cue("B", 11_000, 13_000)
    single = compute_stack_layout([a, b], resolve_one=lambda c: FakeResolved(lines=1), play_res_y=1080)
    multi = compute_stack_layout([a, b], resolve_one=lambda c: FakeResolved(lines=3), play_res_y=1080)
    assert multi.offset_for("B") > single.offset_for("B")


def test_top_safety_clamp():
    a = cue("A", 0, 60_000)
    others = [cue(f"C{i}", 1_000 + i * 500, 60_000) for i in range(40)]
    layout = compute_stack_layout([a, *others], resolve_one=lambda c: FakeResolved(), play_res_y=1080)
    assert all(offset <= 1080 * 0.88 + 0.5 for offset in layout.offsets.values())


def test_disabled_returns_empty():
    a, b = cue("A", 10_000, 12_000), cue("B", 11_000, 13_000)
    layout = compute_stack_layout([a, b], resolve_one=lambda c: FakeResolved(), play_res_y=1080, enabled=False)
    assert layout.offsets == {}


def test_long_handoff_chain_alternates_two_rows_instead_of_climbing():
    rows = [cue(str(i), i * 1000, i * 1000 + 1100) for i in range(100)]
    def resolved(row):
        value = FakeResolved(size=30 + (int(row.id) % 7))
        value._recipe.layout['lineHeightPx'] = 38 + int(row.id) % 11
        return value
    first = compute_stack_layout(rows, resolve_one=resolved, play_res_y=1080)
    second = compute_stack_layout(list(reversed(rows)), resolve_one=resolved, play_res_y=1080)
    # Mixed sizes: a taller caption may not fit a shorter one's row, but the
    # chain never climbs toward the top of the frame.
    assert max(first.offsets.values()) < 200 and not first.warnings
    assert first.offsets == second.offsets
    same = compute_stack_layout(rows, resolve_one=lambda _: FakeResolved(), play_res_y=1080)
    assert all(same.offset_for(str(i)) == 0 for i in range(0, 100, 2))
    assert len({same.offset_for(str(i)) for i in range(1, 100, 2)}) == 1


def test_later_turn_takes_the_bottom_row_once_it_is_free():
    """2026-10-10 (user): A -> A+B -> B+C puts C back in A's row, not above B."""
    rows=[cue('a',0,1100),cue('b',1000,2100),cue('c',2000,3000)]
    layout=compute_stack_layout(rows,resolve_one=lambda _:FakeResolved(),play_res_y=1080)
    assert layout.offset_for('a') == layout.offset_for('c') == 0
    assert layout.offset_for('b') > 0


def test_measured_html_bounds_keep_the_temporal_allocator_available():
    rows = [cue('a', 0, 1100), cue('b', 1000, 2100)]
    def resolved(row):
        value = FakeResolved()
        value._recipe.web_theme = {'enabled': True}
        return value
    layout = compute_stack_layout(rows, resolve_one=resolved, play_res_y=1080,
        bounds_for=lambda c, r: (500, 940, 900, 60))
    assert not layout.warnings and layout.offset_for('b') >= 64


def test_ass_compiler_lifts_overlapping_cues(tmp_path):
    """End to end: overlapping cues produce different \\pos y in compiled ASS."""
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    from twobyteasr.rendering.ass_compiler import compile_ass

    project = SubtitleProject(
        media=StudioMedia(path="D:/fixture.mp4", duration_ms=20_000),
    )
    project.cues = [
        StudioCue(id="A", start_ms=10_000, end_ms=12_000, text="第一条字幕", speaker_id="S01"),
        StudioCue(id="B", start_ms=11_000, end_ms=13_000, text="第二条抢话", speaker_id="S02"),
    ]
    from twobyteasr.caption_style.subtitle_stacking import initialize_project_layout
    initialize_project_layout(project)
    text = compile_ass(project)
    pos_lines = [line for line in text.splitlines() if "\\pos(" in line]
    assert len(pos_lines) >= 2, text[-800:]
    ys = []
    for line in pos_lines:
        part = line.split("\\pos(", 1)[1].split(")", 1)[0]
        ys.append(float(part.split(",")[1]))
    assert len(set(ys)) == 2, f"overlapping cues must sit at different y, got {ys}"
    assert ys[0] < ys[1] or ys[0] > ys[1]  # distinct anchors


def test_a_fraction_of_a_pixel_taller_caption_still_reuses_the_free_row():
    """Real project 2026-10-10: 61.6 vs 62.7 px ink heights cost a whole row."""
    rows = [cue('a', 0, 1100), cue('b', 1000, 2100), cue('c', 2000, 3000)]
    sizes = {'a': 46.0, 'b': 46.0, 'c': 46.4}
    def resolved(row):
        value = FakeResolved()
        value._recipe.layout['lineHeightPx'] = sizes[row.id]
        return value
    layout = compute_stack_layout(rows, resolve_one=resolved, play_res_y=1080)
    assert layout.offset_for('c') == 0 and layout.offset_for('b') > 0
