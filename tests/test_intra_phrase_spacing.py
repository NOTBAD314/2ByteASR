"""Intra-phrase spacing tests (2026-09-20 P4)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.subtitle_rules.intra_phrase_spacing import apply_intra_phrase_spacing


def words(*pairs):
    return [{"text": t, "start_ms": s, "end_ms": e} for t, s, e in pairs]


def test_leading_interjection_with_pause():
    w = words(("嗯", 0, 300), ("魔", 520, 620), ("偶", 620, 720))
    assert apply_intra_phrase_spacing("嗯魔偶首发的吗", w) == "嗯 魔偶首发的吗"


def test_leading_interjection_without_pause_stays():
    w = words(("嗯", 0, 300), ("魔", 320, 620))
    assert apply_intra_phrase_spacing("嗯魔偶首发的吗", w) == "嗯魔偶首发的吗"


def test_leading_interjection_no_evidence_separates():
    assert apply_intra_phrase_spacing("啊狼首发") == "啊 狼首发"


def test_trailing_particle_not_split():
    w = words(("嗯", 0, 300), ("蹲", 520, 720), ("一", 720, 800), ("下", 800, 920), ("不", 920, 1040), ("亏", 1040, 1160), ("啊", 1160, 1260))
    assert apply_intra_phrase_spacing("嗯蹲一下不亏啊", w) == "嗯 蹲一下不亏啊"


def test_repeated_acknowledgement():
    assert apply_intra_phrase_spacing("对对很不错啊嗯") == "对 对 很不错啊嗯"


def test_exact_repetition():
    assert apply_intra_phrase_spacing("有点担心啊有点担心") == "有点担心啊 有点担心"


def test_legitimate_words_not_split():
    for text in ("好像还不错", "这个判断是对的", "还不错的感觉", "好家伙这波"):
        assert " " not in apply_intra_phrase_spacing(text), text


def test_idempotent():
    cases = ["嗯魔偶首发的吗", "对对很不错啊嗯", "有点担心啊有点担心", "啊狼首发", "嗯蹲一下不亏啊"]
    for text in cases:
        once = apply_intra_phrase_spacing(text)
        assert apply_intra_phrase_spacing(once) == once, (text, once)


def test_plain_ascii_space_only():
    out = apply_intra_phrase_spacing("对对很不错啊嗯")
    assert "\u3000" not in out and "  " not in out and "\u200b" not in out


def test_reapplied_with_existing_spaces():
    assert apply_intra_phrase_spacing("嗯 魔偶首发的吗") == "嗯 魔偶首发的吗"
    assert apply_intra_phrase_spacing("对 对 很不错啊嗯") == "对 对 很不错啊嗯"


def test_sentence_mid_ack_with_pause():
    w = words(("看", 0, 200), ("直播", 200, 500), ("的", 500, 600), ("观众", 600, 900),
              ("说", 900, 1050), ("才", 1050, 1150), ("知道", 1150, 1450), ("的", 1450, 1550),
              ("嗯", 1550, 1700), ("对", 1980, 2100), ("对", 2300, 2400))
    out = apply_intra_phrase_spacing("看直播间的观众说才知道的嗯对对", w)
    assert out.endswith("嗯 对 对"), out
