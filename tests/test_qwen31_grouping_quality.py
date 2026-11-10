"""Paid-request-free regressions from the actual ab11 task and bad response."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules import grouping
from twobyteasr.subtitle_rules.grouping_quality import (BoundaryQuality, SourceIndex,
    quality_for_segments, cues_from_quality)
from twobyteasr.subtitle_rules.grouping_quality_request import QualityRetryBudget
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot

FIXTURE = Path(__file__).parent / "fixtures/grouping_contract/qwen31_ab11.json"


@pytest.fixture(autouse=True)
def chinese_task():
    with language_scope("zh"), activate_runtime_context(RuntimeContext(task_language="zh"), legacy=core):
        yield


def sample():
    fixture = json.loads(FIXTURE.read_text("utf-8"))
    rows = [core.SpeechSegment(r["id"],r["start"],r["end"],r["text"],.9,[],speaker=r["speaker"])
            for r in fixture["segments"]]
    return fixture, rows


def provider(monkeypatch, response):
    calls = []
    def complete(messages, **kwargs):
        body = json.loads(messages[1]["content"])
        calls.append((body,kwargs))
        if callable(response):
            return response(body,kwargs)
        return response
    monkeypatch.setattr(grouping,"provider_for_stage",lambda *a,**k:SimpleNamespace(complete=complete))
    monkeypatch.setattr(grouping,"GROUPING_API_RETRIES",1)
    snapshot = resolve_provider_snapshot({"models":{"ai_service":"custom","provider_profiles":{
        "custom":{"base_url":"http://127.0.0.1:1/v1","model":"offline-fixture"}}}})
    return snapshot, calls


def assert_terms_intact(text, boundaries):
    for word in ("这场","虽然","但是","李妹","上一次","六代团","总体来说"):
        start = 0
        while (start := text.find(word,start)) >= 0:
            assert not any(start < cut < start+len(word) for cut in boundaries), word
            start += len(word)


def test_actual_bad_response_has_19_overlength_and_semantic_failures():
    f, rows = sample()
    quality = quality_for_segments(rows, f["acoustic_tokens"])
    issues = quality.inspect(f["model_boundaries"])
    assert len(f["model_boundaries"]) == 42
    assert len(f["source_text"]) == 625
    assert sum(x["kind"] == "length" for x in issues) == 24
    for word in ("这场","虽然","但是","李妹"):
        starts = [i for i in range(len(f["source_text"])) if f["source_text"].startswith(word,i)]
        assert any(x["kind"] == "semantic_boundary" and
            any(i < x["start"] < i+len(word) for i in starts) for x in issues)


def test_actual_response_repairs_keep_all_raw_text_numbers_and_terms():
    f, rows = sample()
    events = []
    cues, final, issues = cues_from_quality(rows,f["model_boundaries"],f["acoustic_tokens"],
        record=lambda name,**data:events.append(dict(event=name,**data)))
    assert "".join(c.text for c in cues) == f["source_text"]
    assert all(core.display_length(c.text) <= 16 for c in cues)
    assert not issues
    assert_terms_intact(f["source_text"],final)
    assert 158 in final and 168 in final  # 两个原来完整、合法的模型断点保持。
    assert next(c for c in cues if "结果" in c.text).text.startswith("结果")
    assert all(0 <= c.start < c.end <= 105.5 for c in cues)
    moves = [e for e in events if e["event"]=="grouping_boundary_move"]
    assert moves and all("old_positions" in e and "new_positions" in e and "reason" in e for e in moves)
    assert moves[0]["old_positions"]==f["model_boundaries"]
    again, again_final, again_issues = cues_from_quality(rows,final,f["acoustic_tokens"])
    assert again_final == final
    assert not again_issues


def test_quality_uses_full_context_and_rejects_the_old_short_tail_damage():
    f, rows = sample()
    q = quality_for_segments(rows,f["acoustic_tokens"])
    safe, _ = q.repair(f["model_boundaries"])
    for word in ("上一次","六代团","总体来说"):
        cut = f["source_text"].index(word)+1
        proposed = sorted(set(safe)|{cut})
        accepted, reason = q.accept_change(safe,proposed)
        assert not accepted and reason == "new_word_or_connective_damage"


def test_raw_unicode_map_keeps_punctuation_case_emoji_and_combining_marks():
    text = "（中文）😀e\u0301 日本語🧑\u200d🚀 12.5kg！"
    index = SourceIndex.build(text)
    for cut in range(1,len(index.content)):
        assert "".join(index.pieces([cut,len(index.content)])) == text
    assert index.content.endswith("125kg")
    with pytest.raises(ValueError):
        SourceIndex.build("İ")


def test_unrepresentable_index_is_reviewable_through_the_full_stage(monkeypatch):
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    snapshot,calls=provider(monkeypatch,'{"boundaries":[3]}')
    rows=[core.SpeechSegment(1,0,2,"İ字幕",.9,[])]
    result=grouping.group_subtitles(rows,use_ai=True,provider_snapshot=snapshot,max_workers=1)
    assert not calls and not result.validated and result.result_status=="local_review"
    assert "".join(c.text for c in result)=="İ字幕"
    finalized=finalize_cues(result,rows,[],[],2.,30,core)
    assert "".join(c.text for c in finalized)=="İ字幕"


@pytest.mark.parametrize("word",["500毫秒","12.5kg","RTX5090","OpenAI","中华人民共和国国务院新闻办公室"])
def test_numbers_units_english_and_indivisible_names_are_not_hard_cut(word,monkeypatch):
    from twobyteasr.subtitle_rules import segmentation
    monkeypatch.setattr(segmentation,"lexical_boundary_terms",lambda:[word])
    q = BoundaryQuality(word)
    cuts, issues = q.repair([len(q.index.content)])
    assert cuts == [len(q.index.content)]
    assert bool(issues) == (len(q.index.content)>14)


def test_connector_ownership_is_contextual_and_nominal_result_stays_intact():
    q = BoundaryQuality("实验结果显示这次成功了但是下一次仍需验证")
    noun_start = q.index.content.index("结果")
    assert noun_start not in q.restarts
    after_conjunction = q.index.content.index("但是")+2
    assert after_conjunction in q.forbidden


def test_legal_word_indices_can_still_strand_a_predicate_modifier():
    q=BoundaryQuality("我们已经开始处理然后继续检查")
    assert 4 in q.forbidden  # 我们已经 | 开始处理
    final,issues=q.repair([4,q.total])
    assert 4 not in final and not issues


def test_short_reaction_and_overlapping_speakers_keep_protected_handoff():
    rows=[core.SpeechSegment(1,0,3,"虽然这个操作很难",.9,[],speaker="A"),
          core.SpeechSegment(2,1,1.3,"啊",.9,[],speaker="B"),
          core.SpeechSegment(3,2.5,4,"但是我还想试试",.9,[],speaker="A")]
    offsets=[]
    cursor=0
    for r in rows:
        cursor+=len(r.text)
        offsets.append(cursor)
    cues, final, issues = cues_from_quality(rows,offsets)
    assert [c.text for c in cues] == [r.text for r in rows]
    assert [c.speaker for c in cues] == [r.speaker for r in rows]
    assert cues[0].end > cues[1].start
    assert not issues


def test_normal_batch_is_one_remote_request(monkeypatch):
    text="先看左边再看右边"
    snapshot,calls=provider(monkeypatch,json.dumps({"boundaries":[4,8]}))
    rows=[core.SpeechSegment(1,0,2,text,.9,[])]
    result=grouping.call_grouping_api(rows,provider_snapshot=snapshot)
    assert len(calls)==1
    assert result.validated
    assert "".join(c.text for c in result)==text


def test_bad_sample_only_retries_small_local_windows_and_keeps_safe_fallback(monkeypatch):
    f,rows=sample()
    def response(body,kwargs):
        if body.get("failed_constraints"):
            return '{"boundaries":[1]}'
        return json.dumps({"boundaries":f["model_boundaries"]})
    snapshot,calls=provider(monkeypatch,response)
    result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,firered_tokens=f["acoustic_tokens"])
    assert 1 < len(calls) <= 3
    assert all(len(body["source_text"]) <= 224 for body,kw in calls[1:])
    assert sum(kw["max_tokens"] for body,kw in calls[1:])<=4096
    assert all(kw["timeout"]<=6 for body,kw in calls[1:])
    assert result.validated
    assert "".join(c.text for c in result)==f["source_text"]
    assert all(len(c.text)<=16 for c in result)


def test_equal_quality_AI_correction_retains_the_local_baseline(monkeypatch):
    f,rows=sample()
    quality=quality_for_segments(rows,f["acoustic_tokens"])
    local,_=quality.repair(f["model_boundaries"])
    changed=[]
    def response(body,kwargs):
        if not body.get("failed_constraints"):
            return json.dumps({"boundaries":f["model_boundaries"]})
        left,right=body["body_range"]
        for old in body["current_boundaries"][:-1]:
            if old in body["required_boundaries"]:
                continue
            for new in body["allowed_boundaries"]:
                proposed=sorted((set(local)-{left+old})|{left+new})
                if new!=old and left < left+new < right and not quality.inspect(proposed):
                    changed.append((left+old,left+new))
                    return json.dumps({"boundaries":[cut-left for cut in proposed if left < cut <= right]})
        return json.dumps({"boundaries":body["current_boundaries"]})
    snapshot,calls=provider(monkeypatch,response)
    events=[]
    monkeypatch.setattr(grouping,"record_run_event",lambda name,**data:events.append(dict(event=name,**data)))
    result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,firered_tokens=f["acoustic_tokens"])
    assert result.validated
    assert [core.display_length(c.text) for c in result] == [b-a for a,b in zip([0,*local],local)]
    assert "".join(c.text for c in result)==f["source_text"]
    retries=[e for e in events if e['event']=='grouping_quality_retry']
    assert retries and all(not e['improved'] for e in retries)
    assert all(e['outcome'] in {'unchanged','rejected'} for e in retries)
    assert all(not e['accepted'] or e['outcome']=='unchanged' for e in retries)


def test_local_correction_input_budget_is_distinct_and_never_dispatched(monkeypatch):
    from twobyteasr.providers import provider_input_budget as budget
    f,rows=sample()
    snapshot,calls=provider(monkeypatch,json.dumps({"boundaries":f["model_boundaries"]}))
    original=budget.prepare_input
    def prepare(messages,**kwargs):
        if json.loads(messages[1]["content"]).get("failed_constraints"):
            raise budget.InputBudgetError({},["fixture"])
        return original(messages,**kwargs)
    monkeypatch.setattr(budget,"prepare_input",prepare)
    events=[]
    monkeypatch.setattr(grouping,"record_run_event",lambda name,**data:events.append(dict(event=name,**data)))
    result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,firered_tokens=f["acoustic_tokens"])
    attempts=[e for e in events if e["event"]=="grouping_quality_retry"]
    assert len(calls)==1 and attempts
    assert all(e["reason"]=="input_budget_conflict" and not e["request_dispatched"] for e in attempts)
    assert result.validated and "".join(c.text for c in result)==f["source_text"]


def test_true_oversized_single_source_still_reaches_multiple_ai_requests(monkeypatch):
    from twobyteasr.providers.provider_input_budget import prepare_input,InputBudgetError
    text="先看左边然后继续向右移动"*350
    rows=[core.SpeechSegment(77,0,len(text)*.13,text,.9,[],speaker="A")]
    def response(body,kwargs):
        q=BoundaryQuality(body["source_text"])
        cuts,_=q.repair([len(q.index.content)])
        return json.dumps({"boundaries":cuts})
    snapshot,calls=provider(monkeypatch,response)
    messages=grouping.call_grouping_api(rows,provider_snapshot=snapshot,_messages_only=True)
    with pytest.raises(InputBudgetError):
        prepare_input(messages,schema=grouping.GROUPING_SCHEMA,max_tokens=snapshot.max_output_tokens,operation="group")
    original=copy.deepcopy(rows)
    result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,_quality_budget=QualityRetryBudget(requests=0),
                                     _source_offsets={77:123})
    assert len(calls)>1
    assert all(body["segments"][0]["source_mapping"]["source_id"]==77 for body,kw in calls)
    assert calls[0][0]["segments"][0]["global_content_start"]==123
    assert calls[-1][0]["segments"][0]["source_mapping"]["global_content_end"]==123+len(text)
    assert "".join(body["source_text"] for body,kw in calls)==text
    assert all(body["read_only_context"] for body,kw in calls)
    assert "".join(c.text for c in result)==text
    assert rows==original


def test_coordinator_uses_file_global_character_spans_in_requests(monkeypatch):
    snapshot,calls=provider(monkeypatch,'{"boundaries":[4,8]}')
    rows=[core.SpeechSegment(4,0,1,"先看左边",.9,[]),core.SpeechSegment(9,1,2,"再看右边",.9,[])]
    result=grouping.group_subtitles(rows,use_ai=True,provider_snapshot=snapshot,max_workers=1)
    assert result.validated and len(calls)==1
    assert [(s["id"],s["global_content_start"],s["global_content_end"]) for s in calls[0][0]["segments"]]==[
        (4,0,4),(9,4,8)]


@pytest.mark.parametrize("category",["timeout","structured_output_truncated","parse_failure"])
def test_request_failures_keep_source_and_are_classified(monkeypatch,category):
    from twobyteasr.providers.ai_providers import AIProviderError
    text="虽然操作困难但是我们仍然继续向前"
    def response(body,kwargs):
        raise AIProviderError("fixture",category=category)
    snapshot,calls=provider(monkeypatch,response)
    events=[]
    monkeypatch.setattr(grouping,"record_run_event",lambda name,**data:events.append((name,data)))
    result=grouping.call_grouping_api([core.SpeechSegment(1,0,3,text,.9,[])],provider_snapshot=snapshot)
    assert result.origin=="fallback" and not result.validated
    assert "".join(c.text for c in result)==text
    expected = "total_timeout" if category == "timeout" else category
    assert any(data.get("category")==expected for name,data in events)


def test_quality_retry_budget_is_shared_and_has_an_absolute_time_cap():
    clock=[0.]
    budget=QualityRetryBudget(clock=lambda:clock[0])
    assert budget.take(10000)==(2048,6.)
    clock[0]=13.
    assert budget.take(10000) is None


def test_filetrans_keeps_sentence_identity_global_spans_word_times_and_time_domain():
    from twobyteasr.recognition.asr import _filetrans_task_rows, _api_transcription_rows
    payload = {"transcripts":[{"channel_id":2,"text":"这场很好但是继续", "sentences":[
        {"sentence_id":41,"begin_time":0,"end_time":2000,"text":"这场很好","speaker_id":0,
         "words":[{"begin_time":0,"end_time":700,"text":"这场"},
                  {"begin_time":800,"end_time":1900,"text":"很好"}]},
        {"sentence_id":42,"begin_time":2100,"end_time":4000,"text":"但是继续","speaker_id":1,
         "words":[{"begin_time":2100,"end_time":2800,"text":"但是"},
                  {"begin_time":2900,"end_time":3900,"text":"继续"}]}]}]}
    converted = _filetrans_task_rows(payload,4.)
    converted["timestamp_source"]="qwen31_native"
    rows = _api_transcription_rows(converted,{"start":10.,"end":14.})
    assert [r["provider_source"]["sentence_id"] for r in rows]==[41,42]
    assert [r["provider_source"]["content_start"] for r in rows]==[0,4]
    assert [r["provider_source"]["content_end"] for r in rows]==[4,8]
    assert all(r["provider_source"]["time_domain"]=="source_seconds" for r in rows)
    assert rows[0]["provider_source"]["valid_word_times"][0]["start"]==10.
    assert rows[1]["tokens"][0]["start"]==12.1
    assert rows[0]["speaker"] != rows[1]["speaker"]


def test_overlapping_native_sentences_use_word_sentence_id_before_time_coincidence():
    from twobyteasr.recognition.asr import _api_transcription_rows
    response={"timestamp_source":"qwen31_native","segments":[
        {"sentence_id":1,"start":0.,"end":2.,"text":"这场比赛"},
        {"sentence_id":2,"start":0.,"end":2.,"text":"虽然困难"}],"words":[
        {"sentence_id":1,"start":0.,"end":1.,"text":"这场"},
        {"sentence_id":1,"start":1.,"end":2.,"text":"比赛"},
        {"sentence_id":2,"start":0.,"end":1.,"text":"虽然"},
        {"sentence_id":2,"start":1.,"end":2.,"text":"困难"}]}
    rows=_api_transcription_rows(response,{"start":10.,"end":12.})
    assert [r["text"] for r in rows]==["这场比赛","虽然困难"]
    assert [[w["text"] for w in r["tokens"]] for r in rows]==[["这场","比赛"],["虽然","困难"]]


def test_new_cache_version_changes_only_grouping_descendants(monkeypatch):
    from twobyteasr.recognition import cache
    from twobyteasr.providers import asr_provider_snapshot
    snapshot = resolve_provider_snapshot({"models":{"ai_service":"custom","provider_profiles":{
        "custom":{"base_url":"http://127.0.0.1:1/v1","model":"offline-fixture"}}}})
    stages=("audio","primary_api","firered_primary","polished","grouped","grouped_local")
    current={s:cache.cache_stage_signature(s,provider_snapshot=snapshot) for s in stages}
    monkeypatch.setattr(cache,"GROUP_LOGIC_VERSION","group-v61-output-thinking-safe-short-spans")
    monkeypatch.setattr(asr_provider_snapshot,"GROUP_CACHE_VERSION","snapshot-validated-grouped-v7-request-policy-comfort")
    old={s:cache.cache_stage_signature(s,provider_snapshot=snapshot) for s in stages}
    for stage in ("audio","primary_api","firered_primary","polished"):
        assert current[stage]==old[stage],stage
    assert current["grouped"]!=old["grouped"]
    assert current["grouped_local"]!=old["grouped_local"]


def test_final_display_save_reopen_translation_and_srt_are_the_same_version(tmp_path):
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.subtitle_rules.grouping_contract import attach_grouping_spans
    from twobyteasr.projects.studio_project import project_from_runtime_cues,save_project,load_project
    from twobyteasr.subtitle_rules import subtitle_translation as translation
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    f,rows=sample()
    cues,_,_=cues_from_quality(rows,f["model_boundaries"],f["acoustic_tokens"])
    for i,cue in enumerate(cues,1):cue.cue_id=i
    attach_grouping_spans(rows,cues)
    finalized=finalize_cues(copy.deepcopy(cues),rows,f["acoustic_tokens"],[],112.8666875,30,core)
    assert [c.text for c in finalized]==[c.text for c in cues]
    project=project_from_runtime_cues(str(tmp_path/"fixture.mp4"),finalized,
        generation_metadata={"language":{"code":"zh"}},initialize_layout=False)
    project.generation_metadata[translation.RECORDS_KEY]=translation._empty_container("en")
    for cue in project.cues:
        translation.set_manual(project,cue.id,"译文 "+cue.id,target="en")
    path=save_project(project,tmp_path/"replay.2byteproj")
    reopened=load_project(path)
    assert [c.text for c in reopened.cues]==[c.text for c in finalized]
    assert reopened.generation_metadata["segmentation_source_spans"]==project.generation_metadata["segmentation_source_spans"]
    exported=export_language_layers(reopened,tmp_path/"export","replay")
    layers={artifact.layer:parse_srt(artifact.path.read_text("utf-8"))[0] for artifact in exported.artifacts}
    assert "".join(c.text for c in layers["original"])==f["source_text"]
    assert [c.text for c in layers["translation"]]==["译文 "+c.id for c in reopened.cues]
    assert [(c.start_ms,c.end_ms) for c in layers["original"]]==[(c.start_ms,c.end_ms) for c in reopened.cues]
    # Saving a manual edit never invokes grouping or rewrites the edit.
    reopened.cues[0].text="人工锁定的修改"
    save_project(reopened,path)
    assert load_project(path).cues[0].text=="人工锁定的修改"
