from types import SimpleNamespace

import moss_firered_pipeline as pipeline
import subtitle_core


def _segment(speaker, start, text="主播发言"):
    return {
        "speaker": speaker,
        "start": float(start),
        "end": float(start + 1.0),
        "text": text,
    }


def test_manual_three_speakers_selects_three_even_if_third_is_sparse():
    rows = []
    rows.extend(_segment("S01", value) for value in (0, 60, 120, 180))
    rows.extend(_segment("S02", value) for value in (10, 70, 130, 190))
    rows.append(_segment("S03", 200, "第三位主播短暂加入"))
    legacy = SimpleNamespace(
        RUNTIME_EXPECTED_SPEAKERS=3,
        content_only=lambda text: text,
        add_review_item=lambda *args, **kwargs: None,
    )

    selected = pipeline.select_host_speakers(rows, 240.0, legacy)

    assert selected == ["S01", "S02", "S03"]


def test_auto_mode_keeps_three_stable_hosts_but_rejects_one_off_voice():
    rows = []
    for speaker, offset in (("S01", 0), ("S02", 5), ("S03", 10)):
        rows.extend(
            _segment(speaker, minute * 60 + offset)
            for minute in range(5)
        )
    rows.append(_segment("S04", 125, "一次性角色声"))
    legacy = SimpleNamespace(
        RUNTIME_EXPECTED_SPEAKERS=0,
        content_only=lambda text: text,
        add_review_item=lambda *args, **kwargs: None,
    )

    selected = pipeline.select_host_speakers(rows, 300.0, legacy)

    assert set(selected) == {"S01", "S02", "S03"}


def test_auto_candidate_span_60_percent_has_named_diagnostics(capsys):
    rows = []
    for label, times in (("S02", [0,60,120,239]), ("S03", [20,80,140,199]), ("S06", [30,90,150,209])):
        rows.extend(_segment(label, start) for start in times)
    reviews = []
    legacy = SimpleNamespace(RUNTIME_EXPECTED_SPEAKERS=0, content_only=lambda text:text,
                             add_review_item=lambda *args, **kwargs: reviews.append(args))
    assert pipeline.MOSS_HOST_MIN_SPAN_RATIO == .60
    selected = pipeline.select_host_speakers(rows, 300, legacy)
    assert set(selected) == {"S02", "S03", "S06"}
    output = capsys.readouterr().out
    assert "timeline_span_ratio=0.6000" in output
    assert "candidate_min_span_ratio=0.60 identity_confirmed=false" in output
    assert any("说话人需要确认" in row for row in reviews)


def _build_legacy(events):
    return SimpleNamespace(
        RUNTIME_EXPECTED_SPEAKERS=0,
        RUNTIME_DIALOGUE_COVERAGE_MODE="all_dialogue",
        content_only=subtitle_core.content_only,
        clean_subtitle_text=subtitle_core.clean_subtitle_text,
        best_alternate_window=lambda text, context: (
            (text, 1.0) if subtitle_core.content_only(text) in subtitle_core.content_only(context)
            else ("", 0.0)
        ),
        add_review_item=lambda *args, **kwargs: None,
        record_run_event=lambda event, **payload: events.append((event, payload)),
        SpeechSegment=subtitle_core.SpeechSegment,
        WordUnit=subtitle_core.WordUnit,
        MIN_SUBTITLE_SECONDS=subtitle_core.MIN_SUBTITLE_SECONDS,
    )


def _coverage_fixture(monkeypatch, mode):
    events = []
    legacy = _build_legacy(events)
    context = SimpleNamespace(expected_speakers=0, dialogue_coverage_mode=mode)
    monkeypatch.setattr(
        pipeline, "select_host_speakers", lambda *args, **kwargs: ["S01"]
    )
    monkeypatch.setattr(
        pipeline,
        "apply_registered_host_voiceprints",
        lambda rows, hosts, *args, **kwargs: (hosts, rows),
    )
    monkeypatch.setattr(pipeline, "_rescue_transient_host_segments", lambda *args: 0)
    payload = {"host_speakers": ["S01"], "segments": [
        {"speaker": "S01", "start": 0.0, "end": 1.0, "text": "主播讲话"},
        {"speaker": "S02", "start": 1.2, "end": 2.2, "text": "角色对白"},
        {"speaker": "S03", "start": 2.4, "end": 3.2, "text": "[音效]"},
    ]}
    speech = [
        {"start": 0.0, "end": 1.0},
        {"start": 1.2, "end": 2.2},
        {"start": 2.4, "end": 3.2},
    ]
    tokens = [
        {"start": 0.0, "end": 1.0, "text": "主播讲话", "confidence": 0.9},
        {"start": 1.2, "end": 2.2, "text": "角色对白", "confidence": 0.9},
    ]
    result = pipeline.build_moss_host_primary_segments(
        payload, tokens, speech, 4.0, legacy, runtime_context=context
    )
    return result, payload, tokens, speech, legacy, context, events


def test_all_dialogue_retains_host_and_npc_but_rejects_sfx(monkeypatch):
    result, *_rest = _coverage_fixture(monkeypatch, "all_dialogue")
    assert [(item.speaker, item.text) for item in result] == [
        ("S01", "主播讲话"),
        ("S02", "角色对白"),
    ]


def test_all_dialogue_retains_three_story_speakers(monkeypatch):
    result, payload, tokens, speech, legacy, context, _events = _coverage_fixture(
        monkeypatch, "all_dialogue"
    )
    payload["segments"][2] = {
        "speaker": "S03", "start": 2.4, "end": 3.4, "text": "第三人对白"
    }
    tokens.append(
        {"start": 2.4, "end": 3.4, "text": "第三人对白", "confidence": 0.9}
    )

    result = pipeline.build_moss_host_primary_segments(
        payload, tokens, speech, 4.0, legacy, runtime_context=context
    )

    assert [(item.speaker, item.text) for item in result] == [
        ("S01", "主播讲话"),
        ("S02", "角色对白"),
        ("S03", "第三人对白"),
    ]


def test_host_only_preserves_old_filter(monkeypatch):
    result, *_rest = _coverage_fixture(monkeypatch, "host_only")
    assert [item.speaker for item in result] == ["S01"]


def test_host_priority_accepts_firered_supported_npc(monkeypatch):
    result, *_rest = _coverage_fixture(monkeypatch, "host_priority")
    assert [item.speaker for item in result] == ["S01", "S02"]


def test_host_priority_restores_qwen_supported_dialogue(monkeypatch):
    result, payload, tokens, speech, legacy, context, events = _coverage_fixture(
        monkeypatch, "host_only"
    )
    context.dialogue_coverage_mode = "host_priority"
    # Remove FireRed support to exercise the Qwen-only restoration path.
    restored, count = pipeline.restore_qwen_supported_dialogue_segments(
        result,
        [{"start": 1.2, "end": 2.2, "text": "角色对白"}],
        payload,
        tokens[:1],
        speech,
        legacy,
        runtime_context=context,
    )
    assert count == 1
    assert [item.speaker for item in restored] == ["S01", "S02"]


def test_japanese_restoration_uses_aligner_tokens_for_timing_only():
    events = []
    legacy = _build_legacy(events)
    context = SimpleNamespace(dialogue_coverage_mode="host_priority", task_language="ja")
    payload = {"host_speakers": ["S01"], "segments": [
        {"speaker": "S01", "start": 0.0, "end": 1.0, "text": "おはよう"},
        {"speaker": "S02", "start": 1.2, "end": 2.2, "text": "ねえ、聞こえた？"},
    ]}
    aligner = [
        {"start": 1.31, "end": 1.52, "text": "ねえ", "source": "qwen-forced-aligner", "alignment_key": "S02@1200-2200"},
        {"start": 1.60, "end": 2.05, "text": "聞こえた", "source": "qwen-forced-aligner", "alignment_key": "S02@1200-2200"},
        {"start": 0.10, "end": 0.90, "text": "おはよう", "source": "qwen-forced-aligner", "alignment_key": "S01@0-1000"},
    ]
    restored, count = pipeline.restore_qwen_supported_dialogue_segments(
        [], [{"start": 1.2, "end": 2.2, "text": "ねえ聞こえた"}], payload, aligner,
        [{"start": 0.0, "end": 2.2}], legacy, runtime_context=context,
    )
    assert count == 1
    (segment,) = restored
    assert segment.speaker == "S02" and segment.text == "ねえ 聞こえた？"
    # The aligner repeats MOSS's own words: no FireRed text or vote, only its own window.
    assert segment.firered_text == "" and segment.alternate_text == "" and segment.firered_start == 0.0
    assert segment.caption_arbitration["forced_alignment_window"] == {
        "start": 1.31, "end": 2.05, "job": "S02@1200-2200", "token_count": 2, "kind": "forced_alignment_span"}


def test_all_dialogue_preserves_overlapping_speakers_with_safety_lock(monkeypatch):
    result, payload, tokens, speech, legacy, context, _events = _coverage_fixture(
        monkeypatch, "all_dialogue"
    )
    payload["segments"][1]["start"] = 0.6
    tokens[1]["start"] = 0.6
    speech[1]["start"] = 0.6
    result = pipeline.build_moss_host_primary_segments(
        payload, tokens, speech, 4.0, legacy, runtime_context=context
    )
    npc = next(item for item in result if item.speaker == "S02")
    assert npc.overlapping_speaker_conflict is True
    assert npc.timing_locked is True
