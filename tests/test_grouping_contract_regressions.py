"""Offline grouping rejection regressions; never contacts a provider."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import subtitle_core as core
from twobyteasr.subtitle_rules import grouping
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context

FIXTURE = Path(__file__).parent / "fixtures/grouping_contract/invalid_responses.json"


def sources():
    return [core.SpeechSegment(1, 0, 2, "先看左边，再看右边", .8, [], speaker="S01")]


def fake_provider(monkeypatch, response, callback=None):
    monkeypatch.setattr(grouping, "GROUPING_API_RETRIES", 1)
    monkeypatch.setattr(grouping, "SECOND_PASS_GROUP_VALIDATION", False)
    calls = []
    def complete(*args, **kwargs):
        calls.append(kwargs)
        if callback:
            callback()
        return response
    monkeypatch.setattr(grouping, "provider_for_stage",
                        lambda *a, **k: SimpleNamespace(complete=complete))
    snapshot = resolve_provider_snapshot({
        "models": {"ai_service": "custom", "provider_profiles": {
            "custom": {"base_url": "http://127.0.0.1:1/v1", "model": "offline-fixture"}}}})
    return snapshot, calls


@pytest.mark.parametrize("case", [case for case in json.loads(FIXTURE.read_text("utf-8-sig"))["cases"]
                                  if not case.get("accept")], ids=lambda row: row["id"])
def test_bad_response_cannot_be_validated_ai(monkeypatch, case):
    snapshot, calls = fake_provider(monkeypatch, case["response"])
    with activate_runtime_context(RuntimeContext(), legacy=core):
        result = grouping.call_grouping_api(sources(), provider_snapshot=snapshot, _packed=True)
    assert calls
    assert result.origin == "fallback"
    assert not result.validated
    assert "".join(cue.text for cue in result) == sources()[0].text


def test_unknown_owner_is_not_ignored_by_batch_validator():
    rows = sources()
    cues = [core.SubtitleCue(1, 0, 2, rows[0].text, speaker="S01"),
            core.SubtitleCue(2, 0, 2, "额外字幕", speaker="S99")]
    assert not grouping._validate_grouped_sources(rows, cues)


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (0, float("inf")), (4, 3), (50, 52)])
def test_matching_text_with_invalid_source_time_is_not_valid(start, end):
    rows = sources()
    assert not grouping._validate_grouped_sources(rows,
        [core.SubtitleCue(1, start, end, rows[0].text, speaker="S01")])


def test_source_changed_during_request_cannot_commit(monkeypatch):
    rows = sources()
    snapshot, calls = fake_provider(monkeypatch, '{"boundaries":[8]}',
                                    callback=lambda: setattr(rows[0], "text", "用户已改成另外一句"))
    with activate_runtime_context(RuntimeContext(), legacy=core):
        with pytest.raises(Exception, match="来源|过期|变化|替换"):
            grouping.call_grouping_api(rows, provider_snapshot=snapshot, _packed=True)


def test_parser_preserves_explicit_index_unit_and_legacy_agreement():
    from twobyteasr.subtitle_rules.grouping_contract import parse_grouping_response
    from twobyteasr.subtitle_rules.text_rules import display_length
    source = "中文😀e\u0301 日本語🧑\u200d🚀"
    total = display_length(source)
    assert total == 6
    assert parse_grouping_response(json.dumps({"boundaries":[2,total]}), source)[0] == [2,total]
    # UTF-16/raw-string endpoint, not the advertised countable unit.
    with pytest.raises(ValueError):
        parse_grouping_response(json.dumps({"boundaries":[len(source)]}), source)
    original = sources()[0].text
    boundaries, _ = parse_grouping_response(
        '{"boundaries":[4,8],"segmented_text":"先看左边，|再看右边"}', original)
    assert boundaries == [4,8]
    assert parse_grouping_response("[4,8]", original)[0] == [4,8]
    with pytest.raises(ValueError):
        parse_grouping_response('{"boundaries":[8],"boundaries":[4,8]}', original)


def test_original_punctuation_emoji_and_combining_mark_restored_atomically():
    from twobyteasr.providers.asr_provider_snapshot import restore_source_text
    source = SimpleNamespace(text="中文😀e\u0301 日本語🧑\u200d🚀")
    cues = [SimpleNamespace(text="中文e"), SimpleNamespace(text="日本語")]
    assert restore_source_text([source], cues)
    assert [cue.text for cue in cues] == ["中文😀e\u0301", "日本語🧑\u200d🚀"]
    bad = [SimpleNamespace(text="中文e"), SimpleNamespace(text="日語")]
    before = [cue.text for cue in bad]
    assert not restore_source_text([source], bad)
    assert [cue.text for cue in bad] == before


def test_normal_overlapping_speakers_pass_but_repeated_source_times_cannot_swap():
    from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result
    rows = [core.SpeechSegment(1,0,2,"重复台词",.8,[],speaker="S01"),
            core.SpeechSegment(2,.5,2.5,"重复台词",.8,[],speaker="S02")]
    cues = [core.SubtitleCue(1,row.start,row.end,row.text,speaker=row.speaker) for row in rows]
    assert validate_grouping_result(rows,cues)
    rows[1].speaker = cues[1].speaker = "S01"
    rows[1].start, rows[1].end = 10, 12
    cues[0].start,cues[0].end,cues[1].start,cues[1].end = 10,12,0,2
    with pytest.raises(ValueError,match="来源范围"):
        validate_grouping_result(rows,cues)


def test_snapshot_changes_for_speaker_timing_and_word_evidence():
    from twobyteasr.subtitle_rules.grouping_contract import capture_grouping_source
    import copy
    original = sources()
    original[0].words = [core.WordUnit(0,.2,"先",.9)]
    snapshot = capture_grouping_source(original,job_id="task",batch_id="1")
    for change in (lambda row:setattr(row,"speaker","S02"),
                   lambda row:setattr(row,"start",.1),
                   lambda row:setattr(row.words[0],"text","后")):
        changed = copy.deepcopy(original)
        change(changed[0])
        with pytest.raises(ValueError,match="来源已变化"):
            snapshot.require_current(changed)
    assert snapshot.identity()["time_domain"] == "source_seconds"


def test_cancelled_no_cache_request_never_returns_fallback(monkeypatch):
    from twobyteasr.recognition.service import CancelledError
    token = SimpleNamespace(is_cancelled=False)
    snapshot,_ = fake_provider(monkeypatch,'{"boundaries":[8]}',
                               lambda:setattr(token,"is_cancelled",True))
    with activate_runtime_context(RuntimeContext(cancellation_token=token),legacy=core):
        with pytest.raises(CancelledError):
            grouping.call_grouping_api(sources(),provider_snapshot=snapshot,_packed=True)


def test_local_cache_is_revalidated_and_invalid_new_result_cannot_escape(tmp_path):
    from twobyteasr.recognition.cache import run_cached_api_batch
    rows=sources(); calls=[]
    cache={"identity":{"sha256":"offline-source"},"cache_dir":str(tmp_path)}
    def run():
        calls.append(1)
        return grouping.fallback_group(rows)
    def execute():
        return run_cached_api_batch("grouped_local",cache,{"source":"fixture"},run,
            encoder=core.serialize_cues,decoder=core.deserialize_cues,
            validator=lambda cues:grouping._validate_grouped_sources(rows,cues))
    with activate_runtime_context(RuntimeContext(),legacy=core):
        execute()
        file=next(tmp_path.glob("api_batches/grouped_local/*.json"))
        payload=json.loads(file.read_text("utf-8"))
        payload["data"][0]["end"]=float("inf")
        file.write_text(json.dumps(payload),encoding="utf-8")
        result=execute()
        assert calls==[1,1] and result[0].end==2 and result.data_validated
        cached=execute()
        assert calls==[1,1] and cached.cache_hit and cached.data_validated and not cached.validated
        with pytest.raises(ValueError,match="未通过来源契约"):
            run_cached_api_batch("grouped_local",cache,{"source":"bad"},lambda:[],
                validator=lambda cues:grouping._validate_grouped_sources(rows,cues))


def test_cache_hit_cancellation_during_validation_is_not_accepted(tmp_path):
    from twobyteasr.recognition.cache import run_cached_api_batch
    from twobyteasr.recognition.service import CancelledError
    token=SimpleNamespace(is_cancelled=False); call=[0]
    rows=sources()
    def validate(cues):
        call[0]+=1
        if call[0]>1:token.is_cancelled=True
        return grouping._validate_grouped_sources(rows,cues)
    with activate_runtime_context(RuntimeContext(cancellation_token=token),legacy=core):
        kwargs=dict(stage="grouped_local",cache_context={"identity":{},"cache_dir":str(tmp_path)},
            dependency={},runner=lambda:grouping.fallback_group(rows),
            encoder=core.serialize_cues,decoder=core.deserialize_cues,validator=validate)
        run_cached_api_batch(**kwargs)
        with pytest.raises(CancelledError):
            run_cached_api_batch(**kwargs)


def test_truncated_split_uses_same_retry_budget(monkeypatch):
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.providers.provider_input_budget import RetryBudget
    snapshot,_ = fake_provider(monkeypatch,"")
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs["batch_index"])
        raise AIProviderError("truncated",category="structured_output_truncated")
    monkeypatch.setattr(grouping,"provider_for_stage",lambda *a,**k:SimpleNamespace(complete=complete))
    rows=[core.SpeechSegment(index,index,index+.8,"保留原文",.8,[],speaker="S01") for index in range(4)]
    with activate_runtime_context(RuntimeContext(),legacy=core):
        result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,_packed=True,
                                         _retry_budget=RetryBudget(1))
    assert len(calls)==2
    assert result.origin=="fallback" and result.data_validated and not result.validated
    assert "".join(c.text for c in result)=="保留原文"*4


def test_postprocessing_cannot_add_unowned_cues(monkeypatch):
    original=grouping.merge_hanging_attribute_cues
    def broken(cues):
        return list(original(cues))+[core.SubtitleCue(99,0,2,"未归属内容",speaker="S99")]
    monkeypatch.setattr(grouping,"merge_hanging_attribute_cues",broken)
    with activate_runtime_context(RuntimeContext(),legacy=core):
        result=grouping.group_subtitles(sources(),use_ai=False)
    assert [(cue.text,cue.speaker) for cue in result]==[(sources()[0].text,"S01")]
    assert result.data_validated and not result.validated


def test_second_pass_conflict_keeps_first_and_shares_budget(monkeypatch):
    from twobyteasr.providers import ai_providers
    from twobyteasr.providers.provider_input_budget import RetryBudget
    snapshot,_=fake_provider(monkeypatch,"")
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs)
        return '{"boundaries":[8],"segmented_text":"先看左边，|再看右边"}'
    monkeypatch.setattr(ai_providers,"provider_for_stage",lambda *a,**k:SimpleNamespace(complete=complete))
    with activate_runtime_context(RuntimeContext(),legacy=core):
        budget=RetryBudget(1)
        assert core.validate_grouping_boundaries_with_llm(sources(),[4,8],
            provider_snapshot=snapshot,retry_budget=budget)==[4,8]
        assert core.validate_grouping_boundaries_with_llm(sources(),[4,8],
            provider_snapshot=snapshot,retry_budget=budget)==[4,8]
    assert len(calls)==1

def test_reused_runtime_object_cannot_commit_to_next_media(monkeypatch):
    from twobyteasr.recognition.service import CancelledError
    context=RuntimeContext(media_index=1,studio_project_path="project-one")
    snapshot,_=fake_provider(monkeypatch,'{"boundaries":[8]}',
        lambda:setattr(context,"media_index",2))
    with activate_runtime_context(context,legacy=core):
        with pytest.raises(CancelledError):
            grouping.call_grouping_api(sources(),provider_snapshot=snapshot,_packed=True)


@pytest.mark.parametrize("language,text", [
    ("en","So we go left here and then we take the big bridge over the river to reach the castle gate."),
    ("ko","오늘은 여기서 시작하고 저쪽으로 가서 다음 방에 들어가 보겠습니다."),
    ("ja","恐ろしいわ すえ恐ろしいわこの子ら。"),
])
def test_full_stage_cache_checks_real_language_outputs(tmp_path,language,text):
    from twobyteasr.recognition.cache import run_cached_stage
    rows=[core.SpeechSegment(1,0,10,text,.8,[],speaker="S01")]
    if language=="en":
        from twobyteasr.subtitle_rules.english_segmentation import group_english
        producer=lambda:group_english(rows)
    elif language=="ko":
        from twobyteasr.subtitle_rules.korean_segmentation import group_korean
        producer=lambda:group_korean(rows)
    else:
        producer=lambda:grouping.group_subtitles(rows,use_ai=False)
    with activate_runtime_context(RuntimeContext(task_language=language),legacy=core):
        result=run_cached_stage("grouped_local",{"identity":{},"cache_dir":str(tmp_path)},producer,
            encoder=core.serialize_cues,decoder=core.deserialize_cues,
            extra_signature={"segments":core.serialize_segments(rows)})
    assert grouping._validate_grouped_sources(rows,result)

def test_corrupt_word_time_cannot_widen_sentence_time_domain():
    rows=sources()
    rows[0].words=[core.WordUnit(1000,1002,rows[0].text,.9)]
    assert not grouping._validate_grouped_sources(rows,
        [core.SubtitleCue(1,1000,1002,rows[0].text,speaker="S01")])


@pytest.mark.parametrize("interruption", [False,True])
def test_cache_candidate_cannot_merge_across_protected_turn(interruption):
    from twobyteasr.subtitle_rules.grouping_contract import validate_grouping_result
    rows=[core.SpeechSegment(1,0,1,"第一句",.8,[],speaker="S01")]
    cues=[core.SubtitleCue(1,0,5,"第一句第二句",speaker="S01")]
    if interruption:
        rows.append(core.SpeechSegment(2,1,2,"插话",.8,[],speaker="S02"))
        cues.append(core.SubtitleCue(2,1,2,"插话",speaker="S02"))
    rows.append(core.SpeechSegment(3,4,5,"第二句",.8,[],speaker="S01"))
    with pytest.raises(ValueError,match="受保护"):
        validate_grouping_result(rows,cues)

def test_case_normalization_that_expands_codepoints_never_sends_ambiguous_offsets(monkeypatch):
    # U+0130 lowercases to two codepoints, unlike indexed_content. Existing
    # generic timeline helpers cannot express that unit; retain source safely.
    rows=[core.SpeechSegment(1,0,1,"İ字幕",.8,[],speaker="S01")]
    snapshot,calls=fake_provider(monkeypatch,'{"boundaries":[3]}')
    with activate_runtime_context(RuntimeContext(),legacy=core):
        result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,_packed=True)
    assert calls==[]
    assert result.origin=="fallback" and result.data_validated
    assert result[0].text=="İ字幕"


def test_huge_numeric_time_is_rejected_without_overflow_exception():
    assert not grouping._validate_grouped_sources(sources(),
        [core.SubtitleCue(1,0,10**1000,sources()[0].text,speaker="S01")])
