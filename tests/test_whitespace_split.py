# -*- coding: utf-8 -*-
"""Razor and AI splits on a pause space leave no edge whitespace (2026-10-12).

Before: cutting "这里怎么办 我们还能挠三下" in its pause produced the left cue
"这里怎么办 " (the space stayed on the left).  The space is the boundary now;
measured word timing of both halves must stay exactly as heard.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.cue_word_alignment import cue_words
from twobyteasr.sentence_refine import build_replacement_cues, validate_action
from twobyteasr.studio_caption_timeline import ensure_independent_captions
from twobyteasr.studio_commands import SpliceCuesCommand, split_cue_command
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_timing import describe_split, split_texts_at, trim_cut_pieces

TEXT = "这里怎么办 我们还能挠三下"
# 600 ms real pause between 办 and 我.
HEARD = [("这", 1000, 1100), ("里", 1100, 1200), ("怎", 1200, 1300), ("么", 1300, 1400),
         ("办", 1400, 1500), ("我", 2100, 2200), ("们", 2200, 2300), ("还", 2300, 2400),
         ("能", 2400, 2500), ("挠", 2500, 2600), ("三", 2600, 2700), ("下", 2700, 2800)]


def _app():
    return QApplication.instance() or QApplication([])


def make_project(independent):
    words = [dict(text=t, start_ms=a, end_ms=b, model="firered") for t, a, b in HEARD]
    row = {"text": TEXT.replace(" ", ""), "start_ms": 1000, "end_ms": 2800, "final_timing_owner": "FireRed",
           "caption_arbitration": {"acoustic_words": words},
           "words": [dict(text=t, start_ms=a, end_ms=b) for t, a, b in HEARD]}
    project = SubtitleProject(
        media=StudioMedia(path="D:/missing.mp4", duration_ms=10000),
        cues=[StudioCue("c1", 1000, 2800, TEXT, speaker_id="S01", evidence_refs=["segment:1"])],
        speakers=[StudioSpeaker(id="S01", name="主播")],
        asr_evidence={"segment:1": row})
    project.validate()
    if independent:
        ensure_independent_captions(project)
    return project


def timed(project, cue):
    words, reason = cue_words(project, cue)
    return reason, [(cue.text[w.char_start:w.char_end], w.start_ms, w.end_ms) for w in words]


def test_cut_helpers_trim_only_the_cut():
    assert split_texts_at(TEXT, 6) == ("这里怎么办", "我们还能挠三下")   # cut after the space
    assert split_texts_at(TEXT, 5) == ("这里怎么办", "我们还能挠三下")   # cut before the space
    assert split_texts_at("对 对 很不错啊 嗯", 4) == ("对 对", "很不错啊 嗯")  # inner pauses stay
    assert split_texts_at("主播投的是对面的", 5) == ("主播投的是", "对面的")    # no space: unchanged
    assert trim_cut_pieces([" 嗯 ", "好 ", " 走 "]) == [" 嗯", "好", "走 "]     # outer edges untouched
    assert trim_cut_pieces(["好", "   "]) == ["好", "   "]                     # degenerate: raw kept


@pytest.mark.parametrize("independent", [False, True])
def test_razor_in_the_pause_keeps_words_and_drops_the_space(independent):
    _app()
    p = make_project(independent)
    cue = p.cues[0]
    before_reason, before_words = timed(p, cue)
    assert before_reason == "exact_token_text" and len(before_words) == 12
    for cut in (1600, 1800, 2050):
        preview = describe_split(cue, cut, project=p)
        assert (preview.left_text, preview.right_text) == ("这里怎么办", "我们还能挠三下")
        assert preview.measured
    stack = QUndoStack()
    stack.push(split_cue_command(p, "c1", preview.split_ms, preview.left_text, preview.right_text))
    left, right = sorted(p.cues, key=lambda c: c.start_ms)
    assert (left.text, right.text) == ("这里怎么办", "我们还能挠三下")
    left_reason, left_words = timed(p, left)
    right_reason, right_words = timed(p, right)
    assert left_reason == right_reason == "exact_token_text"
    assert left_words + right_words == before_words  # every word on its measured interval
    stack.undo()
    assert [c.text for c in p.cues] == [TEXT]
    assert timed(p, p.cues[0]) == (before_reason, before_words)


def test_estimated_razor_cut_on_a_space_drops_it_too():
    cue = StudioCue("x", 0, 8000, "这里怎么办 我们")
    preview = describe_split(cue, 6000)  # no evidence: estimated position 6, right after the space
    assert not preview.measured
    assert (preview.left_text, preview.right_text) == ("这里怎么办", "我们")
    preview = describe_split(cue, 5000)  # position 5, right before the space
    assert (preview.left_text, preview.right_text) == ("这里怎么办", "我们")


@pytest.mark.parametrize("split_after", [4, 5])
def test_ai_sentence_split_on_a_space_keeps_word_timing(split_after):
    _app()
    p = make_project(True)
    cue = p.cues[0]
    _reason, before_words = timed(p, cue)
    action = validate_action(cue.text, {"cue_id": "c1", "action": "split", "split_after_chars": [split_after]})
    assert action is not None
    parts = build_replacement_cues(cue, action, project=p, used_ids={"c1"})
    assert [part.text for part in parts] == ["这里怎么办", "我们还能挠三下"]
    assert [(part.start_ms, part.end_ms) for part in parts] == [(1000, 1500), (2100, 2800)]
    assert not action.estimated_timing
    stack = QUndoStack()
    stack.push(SpliceCuesCommand(p, 0, 1, parts, "AI 断句", None))
    after = [timed(p, part) for part in sorted(p.cues, key=lambda c: c.start_ms)]
    assert [reason for reason, _ in after] == ["exact_token_text", "exact_token_text"]
    assert after[0][1] + after[1][1] == before_words
    stack.undo()
    assert [c.text for c in p.cues] == [TEXT]


def test_ai_split_refuses_a_whitespace_only_piece():
    assert validate_action("好吧   我们走", {"action": "split", "split_after_chars": [1, 4]}) is None
