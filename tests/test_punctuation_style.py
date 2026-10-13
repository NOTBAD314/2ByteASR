"""Punctuation style (2026-10-13): one choice, every output; the manuscript never changes.

Covers the text rules (protected symbols, numerals, glossary spelling, English
spacing, line breaks, idempotency, index maps), the export paths (SRT, TXT,
ASS, JSON, language layers, burn-in snapshot, preview revision), old projects
staying byte-identical, the undoable switch and the previewed manuscript
rewrite that keeps word receipts.
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.punctuation_style import (MODE_ADD, MODE_NONE, MODE_ORIGINAL, project_mode, state_value,
                                          style_cues, style_text)
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

TEXTS = ["大家好 今天来玩 v1.2.3 版本 胜率 98.5% 了", "真的吗？我们上 bilibili.com 看看，好不好。",
         "S0pp 和 Zhe 还有 CHIOCHOO 一个", "温度 -5 度，价格 1,000 元。"]


def make_project(state=None):
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{index}", index * 1000, index * 1000 + 900, text,
                        speaker_id="S01" if index % 2 else "S00")
              for index, text in enumerate(TEXTS)],
        speakers=[StudioSpeaker("S00", "主播"), StudioSpeaker("S01", "嘉宾")],
    )
    if state:
        project.studio_state["punctuation"] = state_value(state)
    project.validate()
    return project


@pytest.mark.parametrize("text", [
    "版本 v1.2.3 与 3.14 还有 12:30 和 1,000", "-5 度 −3.5%", "test.user@example.com", "https://example.com/a?b=1",
    "U.S.A. e.g. Mr. Smith", "don't rock-n-roll", "Node.js C++ C# AT&T R&D",
])
def test_meaningful_symbols_survive_no_punctuation(text):
    styled = style_text(text, MODE_NONE).text
    for token in text.split():
        assert token in styled, (token, styled)


def test_no_punctuation_keeps_words_apart_and_lines():
    assert style_text("Hello,world. How are you?", MODE_NONE).text == "Hello world How are you"
    assert style_text("好，我们走。", MODE_NONE).text == "好 我们走"
    assert style_text("第一行，\n第二行。", MODE_NONE).text == "第一行\n第二行"
    assert style_text("好的...那个", MODE_NONE).text == "好的 那个"


def test_add_punctuation_uses_pauses_and_leaves_latin_spacing():
    assert style_text("大家好 今天来玩 v1.2.3 版本", MODE_ADD).text == "大家好，今天来玩 v1.2.3 版本。"
    assert style_text("えっと そうですね", MODE_ADD).text == "えっと、そうですね。"
    assert style_text("我玩 Valorant 很久", MODE_ADD).text == "我玩 Valorant 很久。"
    assert style_text("see you at bilibili.com", MODE_ADD).text == "see you at bilibili.com"  # no '.' glued to a URL
    assert style_text("真的吗？", MODE_ADD).text == "真的吗？"


@pytest.mark.parametrize("mode", [MODE_ADD, MODE_NONE])
def test_numerals_case_and_glossary_spelling_are_untouched(mode):
    styled = style_text("一个 S0pp 和 Zhe 还有 CHIOCHOO 两个", mode).text
    for token in ("一个", "S0pp", "Zhe", "CHIOCHOO", "两个"):
        assert token in styled
    assert "1" not in styled and "2" not in styled


@pytest.mark.parametrize("mode", [MODE_ADD, MODE_NONE, MODE_ORIGINAL])
@pytest.mark.parametrize("text", TEXTS + ["It's 12:30 now, see you!", "第一行\n第二行 还有"])
def test_styles_are_idempotent_and_map_every_kept_character(mode, text):
    first = style_text(text, mode)
    assert style_text(first.text, mode).text == first.text
    assert len(first.index_map) == len(text)
    for source, target in enumerate(first.index_map):
        if target is not None:
            assert first.text[target] == text[source]


def test_glossary_terms_with_symbols_are_protected():
    styled = style_text("今天用 Mr.Beast. 的方法", MODE_NONE, protected_terms=("Mr.Beast.",)).text
    assert "Mr.Beast." in styled


def test_old_project_without_choice_exports_exactly_as_before(tmp_path):
    from twobyteasr import studio_subtitle_export as export
    project = make_project()
    assert project_mode(project) == MODE_ORIGINAL
    options = export.SubtitleExportOptions(formats=frozenset({"srt", "txt", "json", "ass"}))
    artifacts = export.export_subtitle_artifacts(project, tmp_path, "old", options)
    srt = next(a.path for a in artifacts if a.format == "srt").read_text(encoding="utf-8")
    assert all(text in srt for text in TEXTS)
    payload = json.loads(next(a.path for a in artifacts if a.format == "json").read_text(encoding="utf-8"))
    assert [row["text"] for row in payload["cues"]] == TEXTS and payload["punctuation"] == MODE_ORIGINAL


@pytest.mark.parametrize("mode", [MODE_ADD, MODE_NONE])
def test_every_export_follows_the_choice_and_the_project_is_untouched(tmp_path, mode):
    import copy
    from twobyteasr import studio_subtitle_export as export
    from twobyteasr.ass_compiler import compile_ass
    project = make_project(mode)
    before = copy.deepcopy(project.to_dict())
    expected = [style_text(text, mode).text for text in TEXTS]
    options = export.SubtitleExportOptions(formats=frozenset({"srt", "txt", "json", "ass"}), speaker_mode="both")
    artifacts = export.export_subtitle_artifacts(project, tmp_path / mode, "out", options)
    combined = {a.format: a.path for a in artifacts if not a.speaker_id}
    srt = combined["srt"].read_text(encoding="utf-8")
    txt = combined["txt"].read_text(encoding="utf-8").splitlines()
    ass = combined["ass"].read_text(encoding="utf-8")
    payload = json.loads(combined["json"].read_text(encoding="utf-8"))
    assert txt == expected
    assert all(text in srt for text in expected)
    assert [row["text"] for row in payload["cues"]] == expected
    assert [row["original_text"] for row in payload["cues"]] == TEXTS
    assert [(row["id"], row["start_ms"], row["end_ms"], row["speaker_id"]) for row in payload["cues"]] == [
        (cue.id, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in project.cues]
    assert payload["punctuation"] == mode
    if mode == MODE_NONE:
        assert "，" not in ass.split("[Events]")[1] and "？" not in ass.split("[Events]")[1]
        assert "bilibili.com" in ass and "1,000" in ass and "-5" in ass
    else:
        assert "大家好，今天来玩" in ass
    # Per-speaker files follow the same choice.
    per_speaker = [a.path for a in artifacts if a.speaker_id and a.format == "txt"]
    assert per_speaker and all(line in expected for path in per_speaker
                               for line in path.read_text(encoding="utf-8").splitlines())
    assert compile_ass(project).count("Dialogue:") == len(TEXTS)
    assert project.to_dict() == before  # manuscript, timings, speakers, ids unchanged


def test_language_layers_strip_translation_marks_only_for_no_punctuation(tmp_path):
    from twobyteasr import studio_subtitle_export as export
    from twobyteasr import subtitle_translation as st
    for mode in (MODE_NONE, MODE_ADD):
        project = make_project(mode)
        project.generation_metadata["language"] = {"code": "ja"}
        project.cues[0].text = "行くぞ！"
        records = {"c0": "走了！"}
        project.generation_metadata["translations"] = records
        result = export.export_language_layers(project, tmp_path / mode, "layer", ("translation", "original"))
        paths = {a.layer: a.path for a in result.artifacts}
        translation = paths["translation"].read_text(encoding="utf-8")
        original = paths["original"].read_text(encoding="utf-8")
        if mode == MODE_NONE:
            assert "走了" in translation and "！" not in translation and "行くぞ" in original and "！" not in original
        else:
            assert "走了！" in translation


def test_burn_in_snapshot_and_preview_revision_use_the_choice():
    from twobyteasr.export_timeline import export_project_snapshot
    project = make_project(MODE_NONE)
    snapshot = export_project_snapshot(project)
    assert [cue.text for cue in snapshot.cues] == [style_text(text, MODE_NONE).text for text in TEXTS]
    assert [cue.text for cue in project.cues] == TEXTS
    from twobyteasr.ass_compiler import compile_ass_revision
    from twobyteasr.studio_revisions import StudioRevisionStore
    text = compile_ass_revision(StudioRevisionStore(project).render)  # the native preview path
    assert "看看 好不好" in text and "，" not in text.split("[Events]")[1]


def test_style_cues_returns_copies_and_handles_frozen_render_dtos():
    from twobyteasr.studio_revisions import RenderCueDTO
    project = make_project(MODE_ADD)
    copies = style_cues(project, project.cues)
    assert copies[0] is not project.cues[0] and project.cues[0].text == TEXTS[0]
    dto = RenderCueDTO.capture(project.cues[0])
    from twobyteasr.punctuation_style import style_cues_for_state
    [styled] = style_cues_for_state(project.studio_state, [dto])
    assert styled.text.endswith("。") and dto.text == TEXTS[0]


def test_switch_is_one_undo_step_and_rewrite_keeps_timings(qapp):
    from PySide6.QtGui import QUndoStack
    from types import SimpleNamespace
    from twobyteasr.studio_punctuation import (SetPunctuationStyleCommand, WritePunctuationCommand, apply_style,
                                               permanent_changes)
    project = make_project()
    stack = QUndoStack()
    page = SimpleNamespace(project=project, undo_stack=stack)
    assert apply_style(page, MODE_NONE)
    assert project_mode(project) == MODE_NONE and [c.text for c in project.cues] == TEXTS
    stack.undo()
    assert "punctuation" not in project.studio_state
    stack.redo()
    changes = permanent_changes(project)
    assert [row[0] for row in changes] == ["c1", "c3"]  # lines without marks are left alone
    timings = [(c.id, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues]
    stack.push(WritePunctuationCommand(project, changes))
    assert [c.text for c in project.cues] == [style_text(t, MODE_NONE).text for t in TEXTS]
    assert [(c.id, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues] == timings
    stack.undo()
    assert [c.text for c in project.cues] == TEXTS


def test_rewrite_moves_caption_receipt_indices_with_the_text(qapp):
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio_caption_timeline import KEY
    from twobyteasr.studio_punctuation import WritePunctuationCommand, permanent_changes
    project = make_project(MODE_NONE)
    project.cues[1].text = "好，走"
    project.studio_state[KEY] = {"version": 1, "instances": {"c1": {
        "text": "好，走", "words": [{"text": "好", "char_start": 0, "char_end": 1, "start_ms": 1000, "end_ms": 1300},
                                   {"text": "走", "char_start": 2, "char_end": 3, "start_ms": 1400, "end_ms": 1800}]}}}
    stack = QUndoStack()
    stack.push(WritePunctuationCommand(project, [row for row in permanent_changes(project) if row[0] == "c1"]))
    receipt = project.studio_state[KEY]["instances"]["c1"]
    assert project.cues[1].text == "好 走" and receipt["text"] == "好 走"
    assert [(w["char_start"], w["char_end"]) for w in receipt["words"]] == [(0, 1), (2, 3)]
    assert [w["start_ms"] for w in receipt["words"]] == [1000, 1400]


def test_new_task_default_reaches_new_projects_only():
    from twobyteasr.punctuation_style import default_mode_for_new_tasks
    from twobyteasr.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["switches"]["subtitle_punctuation"] == MODE_ORIGINAL
    assert default_mode_for_new_tasks({"switches": {"subtitle_punctuation": "add"}}) == MODE_ADD
    assert default_mode_for_new_tasks({"switches": {"subtitle_punctuation": "bogus"}}) == MODE_ORIGINAL
    assert default_mode_for_new_tasks({}) == MODE_ORIGINAL


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
