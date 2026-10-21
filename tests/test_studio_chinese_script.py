"""Workbench 简繁 conversion, script-insensitive glossary checks, new text in 繁體 projects (2026-10-19, ADR 0132).

Covers the reverse table (OpenCC tw2s, length-preserving), the one-step
undoable project conversion (text, 原文, timings, speakers, word receipts,
term word overrides, translation status, ``language.script``), the 简繁
toolbar menu, glossary matching through the 简/繁 fold (TermResolver,
proofreading service, proofreading page index and conflicts, two-recognizer
readings, punctuation protected terms, review comparisons), and text that a
繁體 project receives from AI cleanup, re-recognition and model candidates.
"""
from __future__ import annotations

import copy
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.subtitle_rules import chinese_script
from twobyteasr.subtitle_rules.chinese_script import (SIMPLIFIED, TRADITIONAL, fold, for_project, glossary_script,
                                                      project_script, to_simplified, to_traditional)

HANS = "头发干了，之后再说"
HANT = "頭髮幹了，之後再說"


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make_project(texts=(HANS, "OK 好的"), *, script=None, language="zh"):
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{index}", index * 2000, index * 2000 + 1400, text, original_text=text,
                        speaker_id="S01" if index % 2 else "S00")
              for index, text in enumerate(texts)],
        speakers=[StudioSpeaker("S00", "主播"), StudioSpeaker("S01", "嘉宾")],
    )
    project.validate()
    if language is not None:
        project.generation_metadata["language"] = {"code": language}
    if script is not None:
        project.generation_metadata.setdefault("language", {})["script"] = script
    return project


# ---------------------------------------------------------------- tables

@pytest.mark.parametrize("traditional, simplified", [
    (HANT, HANS), ("裡面的麵條很乾淨", "里面的面条很干净"), ("後面那隻貓", "后面那只猫"), ("視頻和軟體", "视频和软体"),
])
def test_reverse_table_converts_back_with_the_same_length(traditional, simplified):
    assert to_simplified(traditional) == simplified
    assert len(to_simplified(traditional)) == len(traditional)


def test_reverse_table_keeps_latin_digits_and_round_trips_common_text():
    assert to_simplified("OK 第 3 局 v1.2") == "OK 第 3 局 v1.2"
    for text in ("今天我们来玩一下这个游戏", "头发干了之后再出发", "这里面的东西都很干净"):
        assert to_simplified(to_traditional(text)) == text


def test_both_tables_are_length_preserving_entry_by_entry():
    for path in (chinese_script.TABLE_PATH, chinese_script.REVERSE_TABLE_PATH):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["chars"] and all(len(k) == len(v) == 1 for k, v in payload["chars"].items())
        assert all(len(k) == len(v) for k, v in payload["phrases"].items())
        assert "OpenCC" in payload["about"]
    assert chinese_script.available(SIMPLIFIED) and chinese_script.available(TRADITIONAL)


def test_project_script_follows_the_recorded_language():
    assert project_script(make_project(language=None)) == SIMPLIFIED
    assert project_script(make_project(script=TRADITIONAL)) == TRADITIONAL
    assert glossary_script(make_project()) is None
    assert glossary_script(make_project(script=TRADITIONAL)) == TRADITIONAL
    assert for_project(HANS, make_project()) == HANS
    assert for_project(HANS, make_project(script=TRADITIONAL)) == HANT
    assert fold(HANS) == fold(HANT) and len(fold(HANT)) == len(HANT)


# ---------------------------------------------------------------- command

def _words(text_pairs):
    return [dict(text=t, char_start=s, char_end=e, start_ms=a, end_ms=b, evidence_ref="seg")
            for t, s, e, a, b in text_pairs]


def _timeline_project():
    from twobyteasr.subtitle_rules.subtitle_translation import source_sha
    from twobyteasr.timeline.studio_caption_timeline import KEY
    project = make_project()
    project.render_settings["_cue_domain"] = "timeline"
    words = _words([("头发", 0, 2, 100, 400), ("干了", 2, 4, 450, 700), ("之后", 5, 7, 800, 1000),
                    ("再说", 7, 9, 1100, 1400)])
    project.studio_state[KEY] = {"version": 1, "instances": {"c0": {
        "text": HANS, "words": words, "word_alignment": "exact_token_text",
        "word_base_words": copy.deepcopy(words)}}}
    project.studio_state["term_word_overrides"] = {"c0": {
        "text": HANS, "alignment_provenance": "case_only",
        "words": [dict(text=w["text"], start_ms=w["start_ms"], end_ms=w["end_ms"]) for w in words]}}
    project.generation_metadata["translation_records"] = {"version": 1, "target": "en", "records": {"c0": {
        "text": "Hair dried, then later", "source_text": HANS, "source_sha": source_sha(HANS),
        "status": "done", "origin": "ai"}}}
    return project


def test_conversion_is_one_undo_step_and_keeps_timing_speakers_words_and_translations(qapp):
    from PySide6.QtGui import QUndoStack
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.studio.studio_chinese_script import convert_project
    from twobyteasr.subtitle_rules.subtitle_translation import DONE, records_of, status_of
    from twobyteasr.timeline.studio_caption_timeline import KEY
    project = _timeline_project()
    before = copy.deepcopy(project)
    timings = [(c.id, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues]
    stack = QUndoStack()
    page = SimpleNamespace(project=project, undo_stack=stack)
    assert convert_project(page, TRADITIONAL)
    assert stack.count() == 1
    assert [c.text for c in project.cues] == [HANT, "OK 好的"]
    assert [c.original_text for c in project.cues] == [HANT, "OK 好的"]
    assert [(c.id, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues] == timings
    assert project.generation_metadata["language"] == {"code": "zh", "script": TRADITIONAL}
    receipt = project.studio_state[KEY]["instances"]["c0"]
    assert receipt["text"] == HANT and [w["text"] for w in receipt["words"]] == ["頭髮", "幹了", "之後", "再說"]
    assert [w["text"] for w in receipt["word_base_words"]] == ["頭髮", "幹了", "之後", "再說"]
    assert [w["text"] for w in project.studio_state["term_word_overrides"]["c0"]["words"]] == [
        "頭髮", "幹了", "之後", "再說"]
    words, reason = cue_words(project, project.cues[0])
    assert reason == "exact_token_text"
    assert [(w.text, w.char_start, w.start_ms) for w in words] == [
        ("頭髮", 0, 100), ("幹了", 2, 450), ("之後", 5, 800), ("再說", 7, 1100)]
    assert status_of(records_of(project)["c0"], project.cues[0].text) == DONE
    stack.undo()
    assert project.cues == before.cues
    assert project.generation_metadata == before.generation_metadata
    assert project.studio_state[KEY] == before.studio_state[KEY]
    assert project.studio_state["term_word_overrides"] == before.studio_state["term_word_overrides"]
    stack.redo()
    assert convert_project(page, SIMPLIFIED)
    assert [c.text for c in project.cues] == [HANS, "OK 好的"]
    assert project.generation_metadata["language"]["script"] == SIMPLIFIED
    assert [w.text for w in cue_words(project, project.cues[0])[0]] == ["头发", "干了", "之后", "再说"]


def test_evidence_aligned_project_keeps_words_after_conversion(qapp):
    from PySide6.QtGui import QUndoStack
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.studio.studio_chinese_script import convert_project
    heard = [("头发", 100, 400), ("干了", 450, 700), ("之后", 800, 1000), ("再说", 1100, 1400)]
    project = make_project([HANS])
    project.cues[0].start_ms, project.cues[0].evidence_refs = 100, ["segment"]
    project.asr_evidence = {"segment": {"words": [dict(text=t, start_ms=a, end_ms=b) for t, a, b in heard]}}
    expected = [(w.char_start, w.start_ms, w.end_ms) for w in cue_words(project, project.cues[0])[0]]
    assert convert_project(SimpleNamespace(project=project, undo_stack=QUndoStack()), TRADITIONAL)
    words, reason = cue_words(project, project.cues[0])
    assert reason == "exact_token_text" and [(w.char_start, w.start_ms, w.end_ms) for w in words] == expected


def test_kana_hangul_lines_and_other_languages_are_left_alone(qapp):
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio.studio_chinese_script import convert_project, is_chinese_project, plan_conversion
    project = make_project([HANS, "これは日本语です", "한국어 文字"])
    assert [change.cue_id for change in plan_conversion(project, TRADITIONAL)] == ["c0"]
    japanese = make_project(["今日は天気"], language="ja")
    assert not is_chinese_project(japanese)
    assert not convert_project(SimpleNamespace(project=japanese, undo_stack=QUndoStack()), TRADITIONAL)
    assert is_chinese_project(make_project(language=None))  # older projects follow Chinese rules


def test_text_already_traditional_is_only_marked_and_undo_restores_no_language(qapp):
    from PySide6.QtGui import QUndoStack
    from twobyteasr.studio.studio_chinese_script import convert_project
    project = make_project([HANT], language=None)
    stack = QUndoStack()
    page = SimpleNamespace(project=project, undo_stack=stack)
    assert convert_project(page, TRADITIONAL)
    assert project.cues[0].text == HANT and project.generation_metadata["language"] == {"script": TRADITIONAL}
    assert not convert_project(page, TRADITIONAL)  # nothing left to do
    stack.undo()
    assert "language" not in project.generation_metadata


def test_toolbar_menu_shows_the_script_and_converts_after_the_preview(qapp, monkeypatch):
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QDialog, QLabel, QMenu, QPushButton
    from twobyteasr.studio import studio_chinese_script as module
    project = make_project()
    stack = QUndoStack()
    page = SimpleNamespace(project=project, undo_stack=stack, chinese_script_button=QPushButton("简繁"),
                           window=lambda: None)
    menu = QMenu()
    module.build_menu(page, menu)
    assert page.chinese_script_button.text() == "字幕简繁转换"
    assert page.chinese_script_actions[SIMPLIFIED].isChecked()
    seen = []

    def exec_(dialog):
        seen.append(dialog.findChild(QLabel, "chineseScriptSummary").text())
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", exec_)
    page.chinese_script_actions[TRADITIONAL].trigger()
    assert seen and "1" in seen[0] and project.cues[0].text == HANT
    assert page.chinese_script_button.text() == "字幕简繁转换" and page.chinese_script_actions[TRADITIONAL].isChecked()
    stack.undo()
    assert page.chinese_script_button.text() == "字幕简繁转换" and project.cues[0].text == HANS
    monkeypatch.setattr(QDialog, "exec", lambda _dialog: QDialog.Rejected)
    page.chinese_script_actions[TRADITIONAL].trigger()
    assert project.cues[0].text == HANS and page.chinese_script_actions[SIMPLIFIED].isChecked()
    page.project = make_project(["今日は"], language="ja")
    module.sync_controls(page)
    assert page.chinese_script_button.isEnabled() and "没有可转换" in page.chinese_script_button.toolTip()


# ---------------------------------------------------------------- glossary

def _snapshot():
    from twobyteasr.glossary.terminology import snapshot_from_pairs
    return snapshot_from_pairs([("巫灵", "乌灵"), ("头法", "头发")])


def test_resolver_folds_only_for_a_traditional_project():
    from twobyteasr.glossary.terminology import TermResolver
    exact, folded = TermResolver(_snapshot()), TermResolver(_snapshot(), script=TRADITIONAL)
    assert exact.resolve("這個巫靈很強").hits == ()  # 简体 projects: unchanged, exact
    assert exact.resolve("这个巫灵很强").text == "这个乌灵很强"
    result = folded.resolve("這個巫靈很強")
    assert result.text == "這個烏靈很強"
    assert [(h.start, h.end, h.source, h.canonical) for h in result.hits] == [(2, 4, "巫靈", "烏靈")]
    assert folded.resolve("頭法很亂").text == "頭髮很亂"
    canonical = folded.resolve("這個烏靈很強")
    assert canonical.hits == () and [h.reason for h in canonical.skipped] == ["already_canonical"]
    # A spelling that differs from its target only by script is canonical too.
    assert folded.resolve("这个乌灵很强").hits == ()


def test_glossary_preview_proposes_traditional_spellings(monkeypatch):
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    from twobyteasr.studio.studio_text_tools import values_from_occurrences
    project = make_project(["這個巫靈很強", "烏靈很強", "這個巫灵很強"], script=TRADITIONAL)
    result = preview_glossary_correction(project, [c.id for c in project.cues], _snapshot(), {}, use_ai=False)
    values = values_from_occurrences(project, list(result.hits))
    assert values == {"c0": "這個烏靈很強", "c2": "這個烏靈很強"}
    # A 简体 project keeps the library's spelling, as before.
    simplified = make_project(["這個巫靈很強"])
    hits = preview_glossary_correction(simplified, ["c0"], _snapshot(), {}, use_ai=False).hits
    assert {h.replacement for h in hits} <= {"乌灵"}


def test_ai_answer_in_simplified_becomes_traditional(monkeypatch):
    import twobyteasr.providers.asr_provider_snapshot as provider
    import twobyteasr.subtitle_rules.polishing as polish
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    monkeypatch.setattr(provider, "resolve_provider_snapshot", lambda *_a, **_kw: SimpleNamespace(
        public_identity=lambda: {"provider": "test", "model": "test"}, timeout_policy=SimpleNamespace(total=10)))
    monkeypatch.setattr(polish, "call_correction_api", lambda rows, *a, **kw: polish.PolishBatchResult(
        {row.segment_id: "头发乾了，之后再说吧" for row in rows}))
    project = make_project(["頭髮乾了，之後再說"], script=TRADITIONAL)
    from twobyteasr.studio.studio_text_tools import values_from_occurrences
    result = preview_glossary_correction(project, ["c0"], _snapshot(), {})
    # Only the model's own edit, in 繁體; 乾 stays as the caption wrote it.
    assert values_from_occurrences(project, list(result.hits)) == {"c0": "頭髮乾了，之後再說吧"}


def test_proofread_page_index_conflicts_and_readings_follow_the_script():
    from twobyteasr.glossary.glossary_proofread import TermIndex, _occurs
    from twobyteasr.recognition.transcript_evidence import evidence_occurrences, project_evidence
    index = TermIndex([("疫病吐息", "skill")], script=TRADITIONAL)
    assert index.occurrences("他放了疫病吐息") == [(3, 7, "疫病吐息")]
    assert TermIndex([("头发", "")], script=TRADITIONAL).occurrences("剪頭髮") == [(1, 3, "頭髮")]
    assert TermIndex([("头发", "")]).occurrences("剪頭髮") == []
    assert _occurs("乌灵", ["烏靈出現了"]) == 0 and _occurs("乌灵", ["烏靈出現了"], fold) == 1
    source, heard = "大家好今天很冷我們走吧", "大家好今天很冷我们走吧"
    # Compared character by character, a 繁體 character looks misheard by both models.
    assert evidence_occurrences(source, heard, heard) == [((8, 9), "們", "们", True, "FireRed+Qwen")]
    assert evidence_occurrences(source, heard, heard, fold=fold) == []
    wrong = "大家好今天很热我们走吧"
    assert evidence_occurrences(source, wrong, wrong, fold=fold) == [((6, 7), "冷", "热", True, "FireRed+Qwen")]
    project = make_project([source], script=TRADITIONAL)
    project.cues[0].evidence_refs = ["r"]
    project.asr_evidence = {"r": dict(start_ms=0, end_ms=1400, text=wrong, moss_text=wrong, firered_text=wrong,
                                      qwen_asr_text=wrong, primary_source="moss-host")}
    hits = project_evidence(project)["c0"][1]
    assert [(span, old, new) for span, old, new, _agreed, _model in hits] == [((6, 7), "冷", "熱")]


def test_punctuation_protects_a_simplified_term_in_traditional_text():
    from twobyteasr.subtitle_rules.punctuation_style import MODE_NONE, style_text
    text = "原神·啟動，出發"
    assert style_text(text, MODE_NONE, protected_terms=("原神·启动",)).text.startswith("原神·啟動")
    assert style_text("原神·启动，出发", MODE_NONE, protected_terms=("原神·启动",)).text.startswith("原神·启动")


def test_review_comparison_and_candidates_ignore_script_only_differences():
    from twobyteasr.subtitle_rules.studio_qc import normalize_spoken_text, review_candidates
    from twobyteasr.subtitle_rules.studio_review import ReviewEvidenceAggregator
    assert normalize_spoken_text(HANT) == normalize_spoken_text(HANS)
    row = dict(start_ms=0, end_ms=1400, text=HANS, moss_text=HANS, firered_text=HANS, qwen_asr_text=HANS,
               qwen_text=HANS, alternate_text=HANS, firered_llm_text=HANS, primary_source="moss-host")
    project = make_project([HANT], script=TRADITIONAL)
    project.cues[0].evidence_refs = ["r"]
    project.asr_evidence = {"r": row}
    candidates = review_candidates(project, project.cues[0])
    assert len(candidates) == 1 and candidates[0].text == HANT
    assert ReviewEvidenceAggregator().aggregate(project, project.cues[0]).models_agree_text
    row = dict(row, qwen_asr_text="头发湿了，之后再说", qwen_text="头发湿了，之后再说")
    project.asr_evidence = {"r": row}
    texts = [c.text for c in review_candidates(project, project.cues[0])]
    assert texts[0] == HANT and "頭髮溼了，之後再說" in texts  # OpenCC s2tw writes 溼


# ---------------------------------------------------------------- new text

def test_ai_cleanup_of_a_traditional_project_stays_traditional():
    from twobyteasr.studio.studio_text_tools import parse_cleanup_payload
    payload = {"changes": [{"cue_id": "c0", "original": HANT, "replacement": "头发干了，之后说"}]}
    traditional = make_project([HANT], script=TRADITIONAL)
    assert [h.replacement for h in parse_cleanup_payload(payload, traditional)] == ["頭髮幹了，之後說"]
    simplified = make_project([HANS])
    payload["changes"][0].update(original=HANS)
    assert [h.replacement for h in parse_cleanup_payload(payload, simplified)] == ["头发干了，之后说"]


def test_rerecognition_of_a_traditional_project_reads_in_traditional(tmp_path, monkeypatch):
    from twobyteasr.studio import studio_reasr
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x")
    project = make_project([HANT], script=TRADITIONAL)
    project.media.path = str(media)
    project.cues[0].evidence_refs = ["r"]
    project.asr_evidence = {"r": {"text": HANS}}

    def fake_ffmpeg(command, **_kwargs):
        from pathlib import Path
        Path(command[-1]).write_bytes(b"RIFF" + b"\0" * 100)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(studio_reasr, "run_hidden_subprocess", fake_ffmpeg)
    result = studio_reasr.run_local_reasr(project, "c0", {"models": {"qwen_asr_backend": "qwen_local"}}, "ffmpeg",
                                          transcriber=lambda *_a, **_kw: [{"text": "头发湿了"}])
    assert result.review_text == "頭髮溼了" and result.recommendation == "頭髮溼了"
    assert result.primary_text == HANT


def test_review_marks_and_batch_replace_offer_traditional_spellings():
    from twobyteasr.glossary.terminology import TermResolver
    from twobyteasr.studio.studio_text_tools import glossary_occurrences
    from twobyteasr.subtitle_rules.review_suggestions import review_suggestions
    rows = review_suggestions("這個巫靈很強", [], resolver=TermResolver(_snapshot(), script=TRADITIONAL), pronouns=False)
    assert [(row.original, [option.text for option in row.options]) for row in rows] == [("巫靈", ["烏靈"])]
    project = make_project(["這個巫靈很強", "烏靈很強"], script=TRADITIONAL)
    hits = glossary_occurrences(project, ["c0", "c1"], snapshot=_snapshot())
    assert [(h.cue_id, h.original, h.replacement, h.span) for h in hits] == [("c0", "巫靈", "烏靈", (2, 4))]
    assert glossary_occurrences(make_project(["這個巫靈很強"]), ["c0"], snapshot=_snapshot()) == []


def test_ai_name_review_in_a_traditional_project_keeps_its_sent_candidate():
    from twobyteasr.glossary.studio_glossary_review import recover_review_edits
    cue = StudioCue("c0", 0, 1000, "這個巫靈很強")
    detail = {"sent_candidates": [{"candidate_id": "k1", "canonical": "乌灵"}],
              "rejected_edits": [{"from": "巫灵", "to": "乌灵", "rule_id": "protected_domain_term",
                                  "candidate_id": "k1"}]}
    output, invalid = recover_review_edits(cue, cue.text, detail, _snapshot(), None, script=TRADITIONAL)
    assert invalid == [] and [(h.original, h.replacement, h.span) for h in output] == [("巫靈", "烏靈", (2, 4))]
    # 简体 project: the model's quote must be the caption's own text, as before.
    output, invalid = recover_review_edits(cue, cue.text, detail, _snapshot(), None)
    assert output == [] and invalid[0]["review_state"] == "invalid_or_unbounded_review_span"
