"""Math formulas in captions, Unicode level (2026-10-16, ADR 0124).

`$…$` formulas in the manuscript are shown as Unicode text in preview, burn-in
and every subtitle export when the project switch is on; nothing changes when
it is off. Covers the converter, the delimiter rules (prices are not math),
protection from the punctuation styles, line wrapping, every export path, the
undoable switch, the menu entry and saving.
"""
import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr import math_text
from twobyteasr.math_text import NBSP, convert, formula_to_unicode, math_spans
from twobyteasr.punctuation_style import MODE_ADD, MODE_NONE, MODE_ORIGINAL, state_value, style_text

TEXTS = [
    r"这个三角形的面积是 $\frac{\sqrt{3}}{4}a^2$",
    r"对它积分：$\int_0^1 x^2\,dx = \frac{1}{3}$",
    r"门票 $5 和 $10，不是公式",
    r"写错的公式 $\fracc{a}{b}$ 原样保留",
]
def plain(text):
    return str(text).replace(NBSP, " ")


def make_project(math=None, punctuation=None):
    project = SubtitleProject(
        project_id="math0000000000000000000000000001",
        media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{index}", index * 1000, index * 1000 + 900, text,
                        speaker_id="S01" if index % 2 else "S00")
              for index, text in enumerate(TEXTS)],
        speakers=[StudioSpeaker("S00", "主播"), StudioSpeaker("S01", "嘉宾")],
    )
    if math is not None:
        project.studio_state[math_text.STATE_KEY] = math_text.state_value(math)
    if punctuation:
        project.studio_state["punctuation"] = state_value(punctuation)
    project.validate()
    return project


@pytest.mark.parametrize("latex, expected", [
    (r"x^2", "x²"), (r"a_{n+1} = a_n + d", "aₙ₊₁ = aₙ + d"), (r"\frac{a+b}{c-d}", "(a+b)/(c-d)"),
    (r"\frac{\sqrt{3}}{4}a^2", "(√3/4)a²"), (r"\sqrt[3]{8} = 2", "∛8 = 2"), (r"\sqrt{x+1}", "√(x+1)"),
    (r"\int_0^1 x^2\,dx = \frac{1}{3}", "∫₀¹ x² dx = 1/3"),
    (r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}", "∑(n = 1…∞) 1/n² = π²/6"),
    (r"\lim_{x \to 0} \frac{\sin x}{x} = 1", "lim(x → 0) (sin x)/x = 1"),
    (r"\alpha \neq \beta", "α ≠ β"), (r"x \in \mathbb{R}", "x ∈ ℝ"), (r"\log_2 3 \approx 1.585", "log₂ 3 ≈ 1.585"),
    (r"\binom{n}{k} \bmod 2", "C(n,k) mod 2"), (r"a \equiv b \pmod{n}", "a ≡ b (mod n)"),
    (r"\angle ABC = 90^\circ", "∠ABC = 90°"), (r"\triangle ABC", "△ABC"), (r"3 \times 4 = 12", "3 × 4 = 12"),
    (r"\left( \frac{a}{b} \right)^2", "(a/b)²"), (r"\displaystyle e^{i\pi} + 1 = 0", "e^(iπ) + 1 = 0"),
])
def test_formulas_become_readable_unicode(latex, expected):
    assert plain(formula_to_unicode(latex)) == expected


@pytest.mark.parametrize("latex", [r"\fracc{a}{b}", r"x^", r"\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}", ""])
def test_what_cannot_be_converted_stays_as_written(latex):
    assert formula_to_unicode(latex) is None
    text = f"看 ${latex}$ 这里"
    assert convert(text)[0] == text


@pytest.mark.parametrize("text, spans", [
    ("门票 $5 和 $10", []),                       # prices: the closing $ follows a space / precedes a digit
    (r"门票 \$5", [(3, 5, None)]),                 # \$ is a dollar sign
    ("$$x$$ 不支持", []),                          # display math is not supported
    ("只有一个 $ 符号", []),
    ("换行 $a\n$ 不配对", []),
    ("$x$和$y$", [(0, 3, "x"), (4, 7, "y")]),
    (r"共 $\$5$ 元", [(2, 7, r"\$5")]),
])
def test_delimiters_follow_the_markdown_rule(text, spans):
    assert math_spans(text) == spans


def test_spaces_inside_a_formula_do_not_break_lines():
    from twobyteasr.caption_text_layout import wrap_caption_text
    text = convert(r"结果是 $\int_0^1 x^2\,dx = \frac{1}{3}$ 对吧")[0]
    assert "∫₀¹" + NBSP + "x²" + NBSP + "dx" in text
    layout = wrap_caption_text(text, len, 16)  # the formula (15 characters) fits a line, not after "结果是 "
    formula = "∫₀¹ x² dx = 1/3".replace(" ", NBSP)
    assert any(formula in line for line in layout.lines), layout.lines
    # Ordinary spaces still break; no-break spaces do not.
    assert wrap_caption_text("aaaa bbbb cccc", len, 9).lines == ("aaaa ", "bbbb cccc")
    assert wrap_caption_text(f"aaaa{NBSP}bbbb cccc", len, 9).lines == (f"aaaa{NBSP}bbbb", " cccc")


@pytest.mark.parametrize("mode", [MODE_ORIGINAL, MODE_ADD, MODE_NONE])
def test_punctuation_styles_never_touch_a_formula(mode):
    text = r"函数 $f(a,b) = 1.5a$，好的 我们 走"
    styled = style_text(text, mode, math=True)
    assert "f(a,b) = 1.5a".replace(" ", NBSP) in styled.text
    assert "$" not in styled.text
    assert len(styled.index_map) == len(text)
    for source, target in enumerate(styled.index_map):
        if target is not None:
            assert styled.text[target] == text[source]
    assert [target for target in styled.index_map if target is not None] == sorted(
        target for target in styled.index_map if target is not None)


def test_add_punctuation_ends_a_line_that_ends_with_a_formula():
    assert style_text(r"面积是 $x^2$", MODE_ADD, math=True).text == "面积是 x²。"
    assert style_text(r"面积是 $x^2$", MODE_ADD).text == r"面积是 $x^2$"  # switch off: as before


def test_switch_off_exports_exactly_as_before(tmp_path):
    from twobyteasr import studio_subtitle_export as export
    options = export.SubtitleExportOptions(formats=frozenset({"srt", "txt", "json", "ass"}))
    outputs = {}
    for label, project in (("absent", make_project()), ("off", make_project(math=False))):
        artifacts = export.export_subtitle_artifacts(project, tmp_path / label, "out", options)
        outputs[label] = {a.format: a.path.read_bytes() for a in artifacts}
    assert outputs["absent"] == outputs["off"]
    payload = json.loads(outputs["off"]["json"])
    assert [row["text"] for row in payload["cues"]] == TEXTS and "math_formulas" not in payload


@pytest.mark.parametrize("punctuation", [None, MODE_NONE])
def test_every_export_shows_formulas_and_the_project_is_untouched(tmp_path, punctuation):
    from twobyteasr import studio_subtitle_export as export
    from twobyteasr.ass_compiler import compile_ass
    project = make_project(math=True, punctuation=punctuation)
    before = copy.deepcopy(project.to_dict())
    expected = [style_text(text, punctuation or MODE_ORIGINAL, math=True).text for text in TEXTS]
    assert plain(expected[0]) == "这个三角形的面积是 (√3/4)a²"
    options = export.SubtitleExportOptions(formats=frozenset({"srt", "txt", "json", "ass"}), speaker_mode="both")
    artifacts = export.export_subtitle_artifacts(project, tmp_path, "out", options)
    combined = {a.format: a.path for a in artifacts if not a.speaker_id}
    srt = combined["srt"].read_text(encoding="utf-8")
    txt = combined["txt"].read_text(encoding="utf-8").splitlines()
    ass = combined["ass"].read_text(encoding="utf-8")
    payload = json.loads(combined["json"].read_text(encoding="utf-8"))
    assert txt == expected
    assert all(text in srt for text in expected)
    assert [row["text"] for row in payload["cues"]] == expected
    assert [row["original_text"] for row in payload["cues"]] == TEXTS
    assert payload["math_formulas"] is True
    events = ass.split("[Events]")[1]
    assert "√3/4" in events and r"\frac｛\\sqrt" not in events and "∫₀¹" in events
    assert "$5" in events  # prices stay
    per_speaker = [a.path for a in artifacts if a.speaker_id and a.format == "txt"]
    assert per_speaker and all(line in expected for path in per_speaker
                               for line in path.read_text(encoding="utf-8").splitlines())
    assert compile_ass(project).count("Dialogue:") == len(TEXTS)
    assert project.to_dict() == before


def test_language_layers_convert_translation_formulas(tmp_path):
    from twobyteasr import studio_subtitle_export as export
    project = make_project(math=True)
    project.generation_metadata["language"] = {"code": "ja"}
    project.generation_metadata["translations"] = {"c0": r"面积是 $x^2$"}
    result = export.export_language_layers(project, tmp_path, "layer", ("translation", "original"))
    paths = {a.layer: a.path for a in result.artifacts}
    assert "面积是 x²" in paths["translation"].read_text(encoding="utf-8")
    assert "(√3/4)a²" in plain(paths["original"].read_text(encoding="utf-8"))


def test_burn_in_snapshot_and_preview_revision_show_formulas():
    from twobyteasr.export_timeline import export_project_snapshot
    from twobyteasr.studio_revisions import StudioRevisionStore
    from twobyteasr.ass_compiler import compile_ass_revision
    project = make_project(math=True)
    snapshot = export_project_snapshot(project)
    assert plain(snapshot.cues[1].text) == "对它积分：∫₀¹ x² dx = 1/3"
    assert [cue.text for cue in project.cues] == TEXTS
    events = compile_ass_revision(StudioRevisionStore(project).render).split("[Events]")[1]
    assert "∫₀¹" in events and r"\int" not in events
    off = make_project(math=False)
    assert r"\\int" in compile_ass_revision(StudioRevisionStore(off).render).split("[Events]")[1]


def test_burn_in_ass_matches_the_preview_with_no_punctuation(tmp_path):
    """The export snapshot is styled once; compiling it must not strip a formula's commas."""
    from twobyteasr.export_timeline import write_export_ass
    from twobyteasr.studio_revisions import StudioRevisionStore
    from twobyteasr.ass_compiler import compile_ass_revision
    project = make_project(math=True, punctuation=MODE_NONE)
    project.cues[0].text = r"函数 $f(a,b) = 1.5a$，好的。"
    path = tmp_path / "burn.ass"
    write_export_ass(project, path)
    burn = path.read_text(encoding="utf-8-sig").split("[Events]")[1]
    preview = compile_ass_revision(StudioRevisionStore(project).render).split("[Events]")[1]
    formula = "f(a,b) = 1.5a".replace(" ", NBSP)
    assert formula in burn and formula in preview
    assert "，" not in burn and "，" not in preview
    assert project.studio_state.get("_cues_display_styled") is None  # only the snapshot is marked


def test_switch_is_one_undo_step_and_survives_saving(qapp, tmp_path):
    from types import SimpleNamespace
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio_project import load_project, save_project
    from twobyteasr.studio_punctuation import apply_math_formulas, permanent_changes
    project = make_project()
    stack = QUndoStack()
    page = SimpleNamespace(project=project, undo_stack=stack)
    assert apply_math_formulas(page, True)
    assert math_text.project_enabled(project) and stack.count() == 1
    assert not apply_math_formulas(page, True)  # already on: no second step
    assert [cue.text for cue in project.cues] == TEXTS
    stack.undo()
    assert math_text.STATE_KEY not in project.studio_state
    stack.redo()
    path = save_project(project, tmp_path / "math.2byteproj")
    assert math_text.project_enabled(load_project(path))
    # Writing punctuation into the manuscript protects formulas and never converts them.
    project.studio_state["punctuation"] = state_value(MODE_NONE)
    project.cues[0].text = r"函数 $f(a,b)$，好的。"
    changes = dict((cue_id, new) for cue_id, _old, new in permanent_changes(project))
    assert changes["c0"] == r"函数 $f(a,b)$ 好的"


def test_menu_entry_toggles_and_follows_undo(qapp):
    from types import SimpleNamespace
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QMenu
    from twobyteasr.studio_punctuation import build_menu
    project = make_project()
    stack = QUndoStack()
    page = SimpleNamespace(project=project, undo_stack=stack)
    menu = QMenu()
    build_menu(page, menu)
    action = page.math_formulas_action
    assert action.isCheckable() and not action.isChecked()
    action.trigger()
    assert action.isChecked() and math_text.project_enabled(project)
    stack.undo()
    assert not action.isChecked() and not math_text.project_enabled(project)
    stack.indexChanged.disconnect()  # the menu goes away before the stack


def test_old_state_values_and_garbage_read_as_off():
    assert not math_text.enabled_from_state({})
    assert not math_text.enabled_from_state({"math_formulas": "yes"})
    assert not math_text.enabled_from_state({"math_formulas": {"enabled": False}})
    assert math_text.enabled_from_state({"math_formulas": {"enabled": True, "version": 1}})


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
