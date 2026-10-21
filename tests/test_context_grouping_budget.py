import json
from types import SimpleNamespace


def test_complete_short_material_keeps_every_id_and_speaker_in_one_request(monkeypatch):
    import subtitle_core as core
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
    rows = [core.SpeechSegment(i + 1, i, i + .8, "保持ID7与重复二十一二十一", .8, [],
        speaker="S01" if i % 2 else "S02") for i in range(50)]
    requests = []
    def complete(batch, **kwargs):
        requests.append((list(batch), kwargs))
        return GroupedBatchResult([core.SubtitleCue(row.segment_id, row.start, row.end,
            row.text, speaker=row.speaker) for row in batch], origin="ai", validated=True)
    monkeypatch.setattr(grouping, "call_grouping_api", complete)
    result = grouping.group_subtitles(rows, use_ai=True)
    assert len(requests) == 1
    assert [row.segment_id for row in requests[0][0]] == list(range(1, 51))
    assert {(cue.speaker, cue.text) for cue in result} == {(row.speaker, row.text) for row in rows}
    assert result.validated and result.origin == "ai"


def test_group_request_receives_shared_scene_and_protected_handoff():
    import subtitle_core as core
    from twobyteasr.subtitle_rules.grouping import call_grouping_api
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary
    library = GlossaryLibrary("game", "用户保存游戏", "8", profile_json='{"game":"瓦罗兰特"}')
    # Constructor contracts are checked explicitly; content_scene receives the same frozen snapshot.
    snapshot = GlossarySnapshot((library,))
    context = RuntimeContext(game_name="", enable_domain_terms=True, glossary_snapshot=snapshot)
    rows = [core.SpeechSegment(1, 0, 1, "CHIOCHOO能奶自己", .8, [], speaker="S01"),
            core.SpeechSegment(2, 1, 2, "autumn来了吗", .8, [], speaker="S02")]
    with activate_runtime_context(context, legacy=core):
        messages = call_grouping_api(rows, _messages_only=True)
    body = json.loads(messages[1]["content"])
    assert body["content_scene"]["domain"] == "瓦罗兰特"
    assert body["content_scene"]["source"] == "enabled_glossary_metadata"
    assert len(body["segments"]) == 2 and body["protected_source_offsets"]
    assert body["source_text"] == "".join(row.text for row in rows)


def test_local_capacity_is_explicit_without_claiming_server_capacity():
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.system.resource_governor import ResourceGovernor
    governor = ResourceGovernor(background_limit=2)
    service = ProviderService(workers=4, governor=governor)
    assert service.scheduling_capacity()["effective_workers"] == 2
    assert service.scheduling_capacity()["account_limit"] is None
    governor.set_playback(True)
    assert service.scheduling_capacity()["effective_workers"] == 1


def test_unknown_qwen_score_never_becomes_low_confidence():
    from moss_firered_pipeline import _record_fused_review_classification
    recorded = []
    legacy = SimpleNamespace(asr_consensus_similarity=lambda a, b: 1.,
        ASR_CONSENSUS_MIN_SIMILARITY=.8, record_run_event=lambda name, **data: recorded.append(data))
    base = dict(firered_text="原文", qwen_text="原文", firered_alignment_confidence=.9)
    rows = [SimpleNamespace(**base, qwen_confidence=0.), SimpleNamespace(**base, qwen_confidence=.2),
            SimpleNamespace(**base, qwen_confidence=0., qwen_confidence_available=True)]
    result = _record_fused_review_classification(legacy, rows, firered_selected=True,
        firered_failed=False, qwen_selected=True, qwen_failed=False)
    assert result["TEXT_CONFIDENCE_UNKNOWN"] == 1
    assert result["TEXT_LOW_CONFIDENCE"] == 2
