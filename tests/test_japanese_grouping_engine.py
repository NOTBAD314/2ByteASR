"""Japanese AI grouping engine: replays of the three 2026-11-25 Japanese reports.

1.json (Qwen local + DeepSeek Flash): 13/13 batches fell back.
Ninja Spy (MOSS long material): every character gap was offered as a phrase
boundary and a retained 30-character line failed the whole task.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace as NS

import pytest

import subtitle_core as core
from twobyteasr.subtitle_rules import japanese_grouping, japanese_morphology
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.text_rules import content_exact

# Ninja Spy shard r004 batch 1, the first six source rows (MOSS).
NINJA_ROWS = [
    (4000001, 3650.17, 3652.47, "R004_S01", "そうかやっと決心してくれたか"),
    (4000002, 3654.13, 3658.97, "R004_S02", "幸いなことに五日後に大安吉日がございます"),
    (4000003, 3659.85, 3662.97, "R004_S02", "周玄はその日がよかろうと存じます"),
    (4000004, 3663.38, 3669.29, "R004_S01", "五日後かよし盛大に周玄を挙げよう殿もさぞお喜びだろう"),
]
# 1.json batch 2 (Qwen 20-25 s windows): the tail with the mid-word pause くださ｜い.
QWEN_ROW = (19, 425.5, 445.25, "S00", "殿様金を返してくださいそれそれ")
# Ninja Spy final failure samples (retained source lines over 26 characters).
NINJA_OVERLONG = [
    "まかり間違えば敵方となる城中へ潜入するなどは危険せんば",
    "そりゃつけ金払ってもらえばいくらでもお代わりを差し上げますよ",
    "確かに月とすっぽん長賤に釣り金釣り合わぬ縁ではあろうとも当たり前だ",
    "しかって左門生涯に一度のこの恋そなたのお心がわからぬままでは心苦しくござそろうと",
]


def rows(spec):
    return [core.SpeechSegment(i, s, e, t, .9, [], speaker=sp) for i, s, e, sp, t in spec]


@pytest.fixture
def no_document(monkeypatch):
    monkeypatch.setattr(japanese_morphology, "_document", lambda: None)


def test_long_material_text_without_morphology_never_offers_every_gap(no_document):
    for _id, _s, _e, _sp, text in NINJA_ROWS:
        result = japanese_grouping.build_candidates(text, hard_max=26)
        total = len(content_exact(text))
        assert result.source == "script_heuristic"
        inner = [c for c in result.candidates if c < total]
        assert len(inner) < total - 1, text            # not every gap
        assert result.candidates[-1] == total
    # The legacy entry point now returns the same engine's answer.
    from twobyteasr.subtitle_rules.segmentation import japanese_break_candidates
    text = "".join(row[4] for row in NINJA_ROWS)
    marks = japanese_break_candidates(text)
    assert len(marks) < len(content_exact(text)) // 2


def test_mandatory_pause_inside_a_word_moves_to_the_phrase_edge(monkeypatch):
    text = QWEN_ROW[4]
    spans = [(0, 4, "殿様金を"), (4, 11, "返してください"), (11, 15, "それそれ")]
    monkeypatch.setattr(japanese_morphology, "document_phrase_spans", lambda content: spans)
    monkeypatch.setattr(japanese_morphology, "document_strong_breaks", lambda content: {11})
    result = japanese_grouping.build_candidates(text, mandatory=[10], hard_max=26)   # くださ｜い
    assert 10 not in result.candidates and result.mandatory == [11]
    assert result.moved_mandatory == [dict(given=10, used=11, reason="mandatory_break_inside_word")]
    assert result.candidates == [4, 11, 15]


def test_stretch_longer_than_the_limit_gets_local_candidates(no_document):
    text = "あのねきのうはずっとうちにいてなにもしないでねてたんだよほんとうに"   # one hiragana run
    result = japanese_grouping.build_candidates(text, hard_max=26)
    edges = [0, *result.candidates]
    assert max(b - a for a, b in zip(edges, edges[1:])) <= 26
    assert result.supplemental


def two_speaker_segments():
    # Ninja Spy: a short line, then a 40-character retained line of another speaker.
    return rows([(1, 3650.17, 3652.47, "R004_S01", NINJA_ROWS[0][4]),
                 (2, 3654.13, 3661.62, "R004_S02", NINJA_OVERLONG[3])])


def test_one_bad_line_does_not_reject_the_valid_lines(no_document):
    segments = two_speaker_segments()
    with language_scope("ja"):
        text = "".join(s.text for s in segments)
        candidates = japanese_grouping.build_candidates(text, mandatory=[14], segment_offsets=[14], hard_max=26)
        total = candidates.total
        sent = []

        def complete(messages):
            sent.append(json.loads(messages[1]["content"]))
            return json.dumps({"windows": [{"id": "w1", "boundaries": [99]}]})   # invalid repair
        # 5 is between marks (6 is the phrase end); 14..54 is one 40-character line.
        cues, receipt = japanese_grouping.finalize_batch(segments, [5, 14, total], candidates, complete=complete)
    assert "".join(c.text for c in cues) == text
    assert [c.grouping_origin for c in cues[:2]] == ["ai_accepted"] * 2
    assert receipt["snapped"] == [dict(given=5, used=6)]
    # Only the failing window went back, with its error and its own marks.
    assert len(sent[0]["windows"]) == 1 and sent[0]["windows"][0]["problem"]["kind"] == "length"
    assert "‹" in sent[0]["windows"][0]["marked_text"]
    assert receipt["rejected_repairs"][0]["reason"] == "not_strictly_increasing_or_wrong_total"
    # The model could not fix it: split locally on legal candidates, labelled local.
    tail = [c for c in cues if c.grouping_origin == "local_fallback_split"]
    assert len(tail) >= 2 and all(len(content_exact(c.text)) <= 26 for c in tail)
    assert receipt["counts"]["ai_accepted"] == 2
    assert {c.speaker for c in cues[:2]} == {"R004_S01"} and {c.speaker for c in tail} == {"R004_S02"}


def test_a_valid_targeted_repair_is_adopted_as_ai(no_document):
    segments = two_speaker_segments()
    with language_scope("ja"):
        text = "".join(s.text for s in segments)
        candidates = japanese_grouping.build_candidates(text, mandatory=[14], segment_offsets=[14])
        total = candidates.total
        window_marks = [c - 14 for c in candidates.candidates if 14 < c < total]
        cut = min(window_marks, key=lambda m: abs(m - (total - 14) / 2))

        def complete(messages):
            return json.dumps({"windows": [{"id": "w1", "boundaries": [cut, total - 14]}]})
        cues, receipt = japanese_grouping.finalize_batch(segments, [14, total], candidates, complete=complete)
    assert [c.grouping_origin for c in cues] == ["ai_accepted", "ai_targeted_correction", "ai_targeted_correction"]
    assert receipt["counts"]["local_fallback_split"] == 0


def test_weak_window_timing_is_not_chopped_for_duration(no_document):
    # 1.json: eight characters inside a 25-second Qwen window.
    segments = rows([(12, 267.0, 292.0, "S00", "あの日あの場所で")])
    with language_scope("ja"):
        candidates = japanese_grouping.build_candidates(segments[0].text)
        cues, receipt = japanese_grouping.finalize_batch(segments, [candidates.total], candidates,
                                                         complete=lambda m: pytest.fail("no repair request"))
    assert [c.text for c in cues] == ["あの日あの場所で"]
    assert cues[0].grouping_origin == "ai_accepted"


def test_retained_japanese_range_is_split_locally_but_stays_pending(no_document, monkeypatch):
    from twobyteasr.subtitle_rules import grouping
    records = []
    monkeypatch.setattr(grouping, "record_run_event", lambda event, **kw: records.append((event, kw)))
    monkeypatch.setattr(grouping, "add_review_item", lambda *a, **k: None)
    segments = rows([(1, 0.0, 6.0, "S00", NINJA_OVERLONG[3]), (2, 6.5, 8.0, "S00", "はい")])
    with language_scope("ja"):
        result = grouping._retain_grouping_range(segments, "AI 断句未完成，保留来源字幕。", 7)
    assert "".join(c.text for c in result) == NINJA_OVERLONG[3] + "はい"
    assert all(len(content_exact(c.text)) <= 26 for c in result)
    assert result[-1].text == "はい"                  # the source boundary stays
    assert all(c.grouping_origin == "source_retained_after_local_rejection" for c in result)
    assert result.origin == "fallback" and result.result_status == "unresolved"
    assert any(event == "grouping_retained_range_local_split" for event, _ in records)


def test_final_gate_keeps_retained_overlong_lines_and_still_fails_unmarked_ones():
    from twobyteasr.subtitle_rules.output import validate_final_cues
    text = NINJA_OVERLONG[1]
    segment = core.SpeechSegment(1, 10.0, 14.15, text, .9, [], speaker="S00")
    retained = core.SubtitleCue(1, 10.0, 14.15, text, speaker="S00")
    retained.grouping_origin = "source_retained_after_local_rejection"
    with language_scope("ja"):
        assert validate_final_cues([retained], [segment], 60.0)[0].text == text
        broken = core.SubtitleCue(1, 10.0, 14.15, text, speaker="S00")
        with pytest.raises(RuntimeError, match="硬性长度上限"):
            validate_final_cues([broken], [segment], 60.0)


def test_request_marks_snapped_mandatory_breaks_and_reads_partial_answers(monkeypatch, tmp_path, no_document):
    from tests.test_stage9_cache_and_budget import config
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.subtitle_rules import grouping
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("fixture", "test"))
    records, prompts = [], []

    def post(*args, **kwargs):
        messages = args[0] if args else kwargs["messages"]
        prompts.append(messages)
        body = json.loads(messages[-1]["content"])
        if "windows" in body:                               # targeted repair: a fragment, rejected
            return json.dumps({"windows": [{"id": w["id"], "boundaries": [1, w["total_length"]]}
                                           for w in body["windows"]]})
        return json.dumps({"boundaries": [body["total_length"]]})   # one long line
    monkeypatch.setattr(grouping, "GROUPING_API_RETRIES", 1)
    monkeypatch.setattr(grouping, "post_chat_completion", post)
    monkeypatch.setattr(grouping, "record_run_event", lambda event, **kw: records.append((event, kw)))
    segments = rows([(1, 0.0, 9.0, "S00", NINJA_OVERLONG[2])])
    context = RuntimeContext(provider_snapshot=resolve_provider_snapshot(config()), task_language="ja",
                             asr_settings_snapshot={"grouping_prompts": {}}, event_log_path=str(tmp_path / "e.jsonl"))
    with activate_runtime_context(context, legacy=core):
        result = grouping.call_grouping_api(segments, provider_snapshot=context.provider_snapshot)
    body = next(kw["request_body"] for event, kw in records if event == "grouping_request_contract")
    total = body["total_length"]
    assert body["break_candidate_count"] < total            # never every character
    assert body["candidate_source"] == "script_heuristic"
    assert "".join(c.text for c in result) == NINJA_OVERLONG[2]
    assert all(len(content_exact(c.text)) <= 26 for c in result)
    assert result.origin == "mixed"                          # local splits are not reported as AI
    receipt = next(kw for event, kw in records if event == "japanese_grouping_receipt")
    assert receipt["counts"]["local_fallback_split"] >= 2 and receipt["rejected_repairs"]
    assert not any(event == "grouping_api_fallback" for event, _ in records)


# --- 2026-11-25 live DeepSeek runs (1.json, 13 batches) -----------------------------------------

def test_over_split_short_pieces_go_back_to_the_model_and_are_joined(no_document):
    segments = rows([(1, 0.0, 6.0, "S00", "一生懸命やれば芸ごとで食べていかれる")])
    with language_scope("ja"):
        candidates = japanese_grouping.build_candidates(segments[0].text)
        marks = [c for c in candidates.candidates]          # the model picked every mark
        sent = []

        def complete(messages):
            body = json.loads(messages[1]["content"])
            sent.append(body)
            window = body["windows"][0]
            return json.dumps({"windows": [{"id": window["id"], "boundaries": [window["total_length"]]}]})
        cues, receipt = japanese_grouping.finalize_batch(segments, marks, candidates, complete=complete)
    assert sent and sent[0]["windows"][0]["problem"]["kind"] == "fragment"
    assert sent[0]["windows"][0]["current_boundaries"]
    assert [c.text for c in cues] == [segments[0].text]
    assert cues[0].grouping_origin == "ai_targeted_correction"


def test_standalone_replies_at_strong_edges_are_not_fragments(monkeypatch):
    text = "はいわかりましたありがとうございます"
    spans = [(0, 2, "はい"), (2, 8, "わかりました"), (8, 18, "ありがとうございます")]
    monkeypatch.setattr(japanese_morphology, "document_phrase_spans", lambda content: spans)
    monkeypatch.setattr(japanese_morphology, "document_strong_breaks", lambda content: {2, 8})
    monkeypatch.setattr(japanese_morphology, "document_word_edges", lambda content: {2, 8})
    segments = rows([(1, 0.0, 3.0, "S00", text)])
    with language_scope("ja"):
        candidates = japanese_grouping.build_candidates(text)
        cues, receipt = japanese_grouping.finalize_batch(segments, [2, 8, 18], candidates,
                                                         complete=lambda m: pytest.fail("no repair"))
    assert [c.text for c in cues] == ["はい", "わかりました", "ありがとうございます"]


def test_fixed_predicates_and_humble_suru_have_no_inner_phrase_edge():
    spans = lambda text, words: japanese_morphology.word_spans(text, words)
    text = "たどり着いたに違いない"
    words = [("たどり", "動詞"), ("着い", "動詞"), ("た", "助動詞"), ("に", "助詞"), ("違い", "名詞"), ("ない", "形容詞")]
    allowed, _ = japanese_morphology.bunsetsu_breaks(text, spans(text, words))
    assert text.index("ない") not in allowed
    text = "おじさんお待たせいたしました"
    words = [("おじ", "名詞"), ("さん", "接尾辞"), ("お", "接頭辞"), ("待た", "動詞"), ("せ", "助動詞"),
             ("いたし", "動詞"), ("まし", "助動詞"), ("た", "助動詞")]
    allowed, _ = japanese_morphology.bunsetsu_breaks(text, spans(text, words))
    assert text.index("いたし") not in allowed and text.index("お待") in allowed
    text = "一生懸命やれば"
    words = [("一生", "名詞"), ("懸命", "形状詞"), ("やれ", "動詞"), ("ば", "助詞")]
    allowed, _ = japanese_morphology.bunsetsu_breaks(text, spans(text, words))
    assert 2 not in allowed and 4 in allowed


# 13.json (比利犬 第二期 13, 2026-11-26) batch 25.1: the rows the request sent.
# The aligner's word times ran past their rows; stage 9 failed with
# "断句候选时间超出其实际来源范围" on both the AI result and the retained fallback.
BILLY_ROWS = [
    (234, 782.72, 787.52, "API_S07", "ニャハハハハわしらが大人しくしてると思ったら大間違いニャ"),
    (235, 787.52, 791.44, "API_S04", "ビリケンたちの邪魔をして仕事を遅らしてやるニャ"),
    (236, 791.44, 793.76, "API_S10", "おらいおらいおらい"),
    (237, 793.76, 794.40, "API_S10", "おらい"),
    (238, 798.08, 799.36, "API_S04", "来ましたニャ"),
    (239, 799.36, 801.92, "API_S07", "ニャハハハ見てろよビリケンめ"),
    (240, 805.68, 808.88, "API_S07", "この手鏡で奴らの目をくらませてやるニャ"),
    (241, 808.88, 810.56, "API_S04", "はいいい考えニャ"),
    (242, 813.12, 814.08, "API_S05", "よし"),
    (243, 814.40, 817.28, "API_S05", "うわぁー！なんだこれまんましい"),
]
BILLY_SHIFT = {234: 1.4, 237: 0.9, 240: -0.8, 243: 1.2}   # seconds the word times drift


def billy_segments():
    segments = []
    for sid, start, end, speaker, text in BILLY_ROWS:
        chars = content_exact(text)
        step = (end - start) / len(chars)
        shift = BILLY_SHIFT.get(sid, 0.0)
        words = [core.WordUnit(start + shift + i * step, start + shift + (i + 1) * step, ch, .9)
                 for i, ch in enumerate(chars)]
        segments.append(core.SpeechSegment(sid, start, end, text, .9, words, speaker=speaker))
    return segments


def test_word_times_past_their_row_never_leave_the_source_envelope(no_document):
    from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result
    segments = billy_segments()
    with language_scope("ja"):
        text = "".join(s.text for s in segments)
        offsets = [28, 51, 60, 63, 69, 83, 102, 110, 112]
        candidates = japanese_grouping.build_candidates(text, mandatory=[28, 51, 63, 69, 83, 102, 110],
                                                        segment_offsets=offsets, hard_max=26)
        cues, receipt = japanese_grouping.finalize_batch(
            segments, [28, 51, 60, 63, 69, 83, 102, 110, 112, 126], candidates, complete=None)
        assert validate_grouping_result(segments, cues)
    assert "".join(c.text for c in cues) == text
    by_id = {s.segment_id: s for s in segments}
    oray = [c for c in cues if c.text.endswith("おらい")][-1]      # ends with row 237
    assert by_id[236].start <= oray.start < oray.end <= by_id[237].end
    tail = [c for c in cues if c.text.endswith("まんましい")][-1]   # its words drift 1.2 s late
    assert tail.end <= by_id[243].end


def test_retained_fallback_with_drifting_word_times_keeps_the_task_alive(no_document, monkeypatch):
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result
    records = []
    monkeypatch.setattr(grouping, "record_run_event", lambda event, **kw: records.append((event, kw)))
    monkeypatch.setattr(grouping, "add_review_item", lambda *a, **k: None)
    segments = billy_segments()
    with language_scope("ja"):
        result = grouping._retain_grouping_range(segments, "AI 断句未完成，保留来源字幕。", "25.1")
        assert validate_grouping_result(segments, result)
    assert "".join(c.text for c in result) == "".join(s.text for s in segments)
    assert all(len(content_exact(c.text)) <= 26 for c in result)     # the 28-character line was split
    assert any(event == "grouping_retained_range_local_split" for event, _ in records)


def test_retained_fallback_keeps_source_lines_when_the_split_breaks_the_contract(no_document, monkeypatch):
    from twobyteasr.subtitle_rules import grouping
    records = []
    monkeypatch.setattr(grouping, "record_run_event", lambda event, **kw: records.append((event, kw)))
    monkeypatch.setattr(grouping, "add_review_item", lambda *a, **k: None)
    segments = billy_segments()

    def bad_split(rows, cues):
        broken = copy.deepcopy(cues)
        broken[0].end = rows[-1].end + 5.0             # claims seconds of another source
        return broken
    monkeypatch.setattr(grouping, "_locally_split_retained_japanese", bad_split)
    with language_scope("ja"):
        result = grouping._retain_grouping_range(segments, "AI 断句未完成，保留来源字幕。", "25.1")
    assert [c.text for c in result] == [s.text for s in segments]
    assert [(c.start, c.end) for c in result] == [(s.start, s.end) for s in segments]
    assert any(event == "grouping_retained_range_split_dropped" for event, _ in records)
