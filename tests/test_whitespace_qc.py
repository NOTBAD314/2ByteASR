# -*- coding: utf-8 -*-
"""Studio QC whitespace rules (2026-10-12).

A single half-width space between CJK characters is the product's pause
spacing ("有点担心 有点担心", "对 布丁") — not an error, and the safe fix must
not delete it.  Edge whitespace, doubled spaces, full-width/NBSP/zero-width
spaces stay flagged.  Existing projects are only cleaned through the explicit,
undoable safe fix, which carries word receipts and term overrides along.
"""
from __future__ import annotations

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.cue_word_alignment import cue_words
from twobyteasr.studio_caption_timeline import KEY, ensure_independent_captions
from twobyteasr.studio_commands import ApplySafeFixesCommand
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_qc import QCResult, SubtitleQCEngine, build_safe_fix_plan, normalize_safe_text
from twobyteasr.studio_runtime_state import state_for


def _app():
    return QApplication.instance() or QApplication([])


def flags(text):
    project = SubtitleProject(media=StudioMedia(path="x.flv", duration_ms=9000))
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    project.cues.append(StudioCue("s1", 1000, 4200, text, speaker_id="S01"))
    engine = SubtitleQCEngine()
    result = QCResult(engine.evaluate_cues(engine.build_context(project), list(project.cues)))
    return {issue.issue_type for issue in result.issues_by_cue.get("s1", ())}


@pytest.mark.parametrize("text", [
    "有点担心 有点担心", "对 布丁", "没事 开一把就知道了", "对的 对的", "嗯 魔偶首发的嗎",
    "对 对 很不错啊 嗯", "OK let's go 走", "Team Liquid 赢了",
])
def test_intentional_single_spaces_are_not_flagged(text):
    assert "extra_spaces" not in flags(text)
    assert normalize_safe_text(text) == text


@pytest.mark.parametrize("text, fixed", [
    ("这里怎么办 ", "这里怎么办"),
    (" 我们还能挠三下", "我们还能挠三下"),
    ("对的  对的", "对的 对的"),
    ("有点担心\u3000有点担心", "有点担心 有点担心"),
    ("对\u00a0布丁", "对 布丁"),
    ("没事\u200b开一把", "没事开一把"),
    ("\ufeff嗯 好", "嗯 好"),
    ("好 ？", "好？"),
])
def test_format_junk_is_flagged_and_safely_fixable(text, fixed):
    assert "extra_spaces" in flags(text)
    assert normalize_safe_text(text) == fixed
    assert normalize_safe_text(fixed) == fixed  # idempotent


def make_project():
    heard = [("这", 1000, 1100), ("里", 1100, 1200), ("怎", 1200, 1300), ("么", 1300, 1400),
             ("办", 1400, 1500)]
    row = {"text": "这里怎么办", "start_ms": 1000, "end_ms": 1500, "final_timing_owner": "FireRed",
           "caption_arbitration": {"acoustic_words": [dict(text=t, start_ms=a, end_ms=b, model="firered")
                                                      for t, a, b in heard]},
           "words": [dict(text=t, start_ms=a, end_ms=b) for t, a, b in heard]}
    project = SubtitleProject(
        media=StudioMedia(path="D:/missing.mp4", duration_ms=10000),
        cues=[StudioCue("junk", 1000, 1500, "\u3000这里怎么办 ", speaker_id="S01", evidence_refs=["segment:1"]),
              StudioCue("pause", 3000, 4000, "有点担心 有点担心", speaker_id="S01"),
              StudioCue("term", 5000, 6000, "BerLIN  守住", speaker_id="S01")],
        speakers=[StudioSpeaker(id="S01", name="主播")],
        asr_evidence={"segment:1": row})
    project.validate()
    ensure_independent_captions(project)
    project.studio_state["term_word_overrides"] = {"term": {
        "text": "BerLIN  守住", "alignment_provenance": "case_only", "time_domain": "cue",
        "words": [{"text": "BerLIN", "start_ms": 5000, "end_ms": 5400},
                  {"text": "守", "start_ms": 5500, "end_ms": 5700}, {"text": "住", "start_ms": 5700, "end_ms": 5900}]}}
    return project


def test_safe_fix_is_explicit_undoable_and_keeps_word_state_consistent():
    _app()
    project = make_project()
    junk = project.cues[0]
    before_words, before_reason = cue_words(project, junk)
    assert before_reason == "exact_token_text"
    term_words, term_reason = cue_words(project, project.cues[2])
    assert term_reason == "exact_token_text"
    snapshot = (copy.deepcopy(project.cues), copy.deepcopy(project.studio_state))

    plan = build_safe_fix_plan(project)
    # Preparing the plan never touches the project (no silent rewrite).
    assert (project.cues, project.studio_state) == snapshot
    assert [cue.text for cue in plan.cues] == ["这里怎么办", "有点担心 有点担心", "BerLIN 守住"]
    assert plan.text_format_count == 2

    stack = QUndoStack()
    revision = state_for(project).revision
    stack.push(ApplySafeFixesCommand(project, plan))
    assert state_for(project).revision > revision
    assert [cue.text for cue in project.cues] == ["这里怎么办", "有点担心 有点担心", "BerLIN 守住"]
    receipt = project.studio_state[KEY]["instances"]["junk"]
    assert receipt["text"] == "这里怎么办"
    assert [(w["char_start"], w["char_end"]) for w in receipt["words"]] == [(i, i + 1) for i in range(5)]
    assert project.studio_state["term_word_overrides"]["term"]["text"] == "BerLIN 守住"
    words, reason = cue_words(project, project.cues[0])
    assert reason == "exact_token_text"
    assert [(w.start_ms, w.end_ms) for w in words] == [(w.start_ms, w.end_ms) for w in before_words]
    assert [project.cues[0].text[w.char_start:w.char_end] for w in words] == list("这里怎么办")
    words, reason = cue_words(project, project.cues[2])
    assert reason == "exact_token_text"
    assert [(w.start_ms, w.end_ms) for w in words] == [(w.start_ms, w.end_ms) for w in term_words]

    stack.undo()
    assert (project.cues, project.studio_state) == snapshot
    stack.redo()
    assert project.studio_state[KEY]["instances"]["junk"]["text"] == "这里怎么办"
    assert project.studio_state["term_word_overrides"]["term"]["text"] == "BerLIN 守住"
