"""Japanese -> Chinese subtitle translation core (no network; fake provider)."""
import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr import subtitle_translation as st
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

JA = [
    "行くぞ！", "ちょっと待って、まだ準備できてない", "やばい", "マジで", "このボス強すぎる",
    "回復して！", "ナイス！", "えっ、何それ", "もう一回やろう", "おつかれさまでした",
]
ZH = {
    "行くぞ！": "走了！", "ちょっと待って、まだ準備できてない": "等一下，我还没准备好", "やばい": "糟了",
    "マジで": "真的假的", "このボス強すぎる": "这个Boss太强了", "回復して！": "快回血！", "ナイス！": "漂亮！",
    "えっ、何それ": "诶，那是什么", "もう一回やろう": "再来一次吧", "おつかれさまでした": "辛苦了",
}


def make_project(texts=JA, *, language="ja"):
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=600_000),
        cues=[StudioCue(f"c{index}", index * 1000, index * 1000 + 900, text,
                        speaker_id="S01" if index % 2 else "S00")
              for index, text in enumerate(texts)],
        speakers=[StudioSpeaker("S00", "主播"), StudioSpeaker("S01", "S01")],
    )
    project.validate()
    if language:
        project.generation_metadata["language"] = {"code": language}
    return project


def cue(project, cue_id):
    return next(item for item in project.cues if item.id == cue_id)


class FakeProvider:
    provider_id = "fake-provider"
    model = "fake-model"

    def __init__(self, responder=None):
        self.calls = []
        self.responder = responder or self.translate_all

    @staticmethod
    def translate_all(payload, call_no):
        return {"items": [{"id": line["id"], "translation": ZH.get(line["text"], "中文" + line["id"])}
                          for line in payload["lines"] if line["translate"]]}

    def structured_complete(self, messages, schema, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.calls.append({"messages": messages, "schema": schema, "kwargs": kwargs, "payload": payload})
        return self.responder(payload, len(self.calls))


def run(project, provider, ids=None, **kwargs):
    kwargs.setdefault("target", "zh-Hans")
    kwargs.setdefault("retry_wait", lambda seconds: True)
    return st.translate(project, ids, provider, **kwargs)


# --- migration -------------------------------------------------------------

def test_migrate_from_legacy_dict_is_idempotent():
    project = make_project()
    project.generation_metadata["translations"] = {"c0": "走了！", "gone": "旧译文", "c2": ""}
    assert st.migrate(project) is True
    records = project.generation_metadata["translation_records"]["records"]
    assert set(records) == {"c0", "gone"}
    assert records["c0"]["origin"] == "manual" and records["c0"]["legacy"] is True
    assert records["c0"]["source_sha"] == st.source_sha(cue(project, "c0").text)
    assert st.cue_status(project, cue(project, "c0")) == "manual"
    assert st.cue_status(project, cue(project, "c1")) == "untranslated"
    frozen = copy.deepcopy(project.generation_metadata)
    assert st.migrate(project) is False
    assert project.generation_metadata == frozen


def test_project_without_translations_is_untouched():
    project = make_project()
    assert st.migrate(project) is False
    assert "translation_records" not in project.generation_metadata
    assert st.sync_render_view(project) == {}
    assert "translations" not in project.generation_metadata
    assert st.translation_view(project)["c0"]["status"] == "untranslated"


def test_legacy_view_edit_is_adopted_as_manual():
    project = make_project()
    apply_all(project)
    project.generation_metadata["translations"]["c1"] = "等等，我还没好"  # old SetCueTranslationCommand
    assert st.migrate(project) is True
    record = st.records_of(project)["c1"]
    assert record["origin"] == "manual" and record["text"] == "等等，我还没好"
    assert record["previous"][0]["text"] == "等一下，我还没准备好"


def apply_all(project, provider=None, **kwargs):
    result = run(project, provider or FakeProvider(), **kwargs)
    st.apply_translation_result(project, result)
    return result


# --- derived status ---------------------------------------------------------

def test_status_follows_text_edit_and_undo():
    project = make_project()
    apply_all(project)
    target = cue(project, "c4")
    assert st.cue_status(project, target) == "done"
    original = target.text
    target.text = "このボス強すぎるだろ"
    assert st.cue_status(project, target) == "needs_update"
    assert st.sync_render_view(project)["c4"] == "这个Boss太强了"  # still rendered, UI flags it
    target.text = original
    assert st.cue_status(project, target) == "done"
    assert st.cue_status(project, target, target="zh-Hant") == "needs_update"


def test_split_and_merge_statuses_and_candidates():
    from twobyteasr.studio_commands import merge_cues_command, split_cue_command

    project = make_project()
    apply_all(project)
    split = split_cue_command(project, "c1", 1500, "ちょっと待って、", "まだ準備できてない")
    split.redo()
    right = next(item.id for item in project.cues if item.id.startswith("c1-split-"))
    assert st.cue_status(project, "c1") == "needs_update"
    assert st.cue_status(project, right) == "untranslated"
    candidates = {item["cue_id"]: item for item in st.split_merge_candidates(project)}
    assert set(candidates) == {"c1", right}
    for item in candidates.values():
        assert item["kind"] == "split"
        assert item["parents"][0]["translation"] == "等一下，我还没准备好"
    # Never copied or divided: the right half has no translation at all.
    assert right not in st.sync_render_view(project)
    split.undo()
    assert st.cue_status(project, "c1") == "done"

    merge = merge_cues_command(project, ["c2", "c3"])
    merge.redo()
    assert st.cue_status(project, "c2") == "needs_update"
    [merged] = st.split_merge_candidates(project)
    assert merged["kind"] == "merge"
    assert [parent["cue_id"] for parent in merged["parents"]] == ["c2", "c3"]
    assert "c3" in st.records_of(project)  # gone cue keeps its record for undo
    assert "c3" not in st.sync_render_view(project)
    merge.undo()
    assert st.cue_status(project, "c3") == "done"
    assert st.sync_render_view(project)["c3"] == "真的假的"


def test_split_reference_reaches_the_prompt():
    from twobyteasr.studio_commands import split_cue_command

    project = make_project()
    apply_all(project)
    split_cue_command(project, "c1", 1500, "ちょっと待って、", "まだ準備できてない").redo()
    provider = FakeProvider()
    ids = [item["cue_id"] for item in st.split_merge_candidates(project)]
    run(project, provider, ids)
    lines = {line["id"]: line for line in provider.calls[0]["payload"]["lines"]}
    right = next(cue_id for cue_id in ids if "-split-" in cue_id)
    assert lines[right]["reference"] == [{"text": "ちょっと待って、まだ準備できてない",
                                          "translation": "等一下，我还没准备好"}]


# --- manual protection ------------------------------------------------------

def test_manual_record_is_never_overwritten_by_ai():
    project = make_project()
    before, after = st.set_manual(project, "c0", "冲啊！")
    assert before["translation_records"] is None and after["translations"] == {"c0": "冲啊！"}
    assert st.cue_status(project, "c0") == "manual"
    result = run(project, FakeProvider())
    assert result.skipped_manual == ("c0",)
    assert result.suggestions["c0"].text == "走了！"
    st.apply_translation_result(project, result)
    assert st.records_of(project)["c0"]["text"] == "冲啊！"
    assert project.generation_metadata["translations"]["c0"] == "冲啊！"
    # Without suggestions no request is spent on the manual cue.
    provider = FakeProvider()
    result = run(project, provider, ["c0"], suggest_for_manual=False)
    assert provider.calls == [] and result.skipped_manual == ("c0",) and not result.suggestions
    # The person accepts the suggestion explicitly.
    suggested = run(project, FakeProvider(), ["c0"])
    st.accept_suggestions(project, suggested)
    record = st.records_of(project)["c0"]
    assert record["text"] == "走了！" and record["origin"] == "ai"
    assert record["previous"][0] == {**record["previous"][0], "text": "冲啊！", "origin": "manual"}


def test_overwrite_manual_and_mid_run_manual_edit():
    project = make_project()
    st.set_manual(project, "c0", "冲啊！")
    result = run(project, FakeProvider(), ["c0"], overwrite_manual=True)
    st.apply_translation_result(project, result)
    assert st.records_of(project)["c0"]["text"] == "走了！"
    # A manual edit made while a run was in flight wins at apply time.
    source = st.translation_source(project)
    result = run(source, FakeProvider(), ["c2"])
    st.set_manual(project, "c2", "完了")
    st.apply_translation_result(project, result)
    assert st.records_of(project)["c2"]["text"] == "完了"
    assert result.suggestions["c2"].text == "糟了"


def test_legacy_records_can_be_replaced_with_overwrite_legacy():
    project = make_project()
    project.generation_metadata["translations"] = {"c0": "旧版"}
    st.migrate(project)
    result = run(project, FakeProvider(), ["c0"], overwrite_legacy=True)
    st.apply_translation_result(project, result)
    assert st.records_of(project)["c0"]["text"] == "走了！"
    st.set_manual(project, "c0", "人工")
    result = run(project, FakeProvider(), ["c0"], overwrite_legacy=True)
    assert result.skipped_manual == ("c0",)


def test_manual_clear_makes_cue_untranslated():
    project = make_project()
    apply_all(project)
    st.set_manual(project, "c3", "")
    assert st.cue_status(project, "c3") == "untranslated"
    assert "c3" not in project.generation_metadata["translations"]
    assert st.records_of(project)["c3"]["previous"][0]["text"] == "真的假的"


# --- batching ---------------------------------------------------------------

def test_plan_batches_sizes_and_context():
    texts = [f"テスト{index}です" for index in range(100)]
    project = make_project(texts)
    batches = st.plan_batches(project, None, max_items=40, max_chars=10_000, context_cues=3)
    assert [len(batch.target_ids) for batch in batches] == [40, 40, 20]
    second = batches[1]
    assert [line.id for line in second.context] == ["c37", "c38", "c39", "c80", "c81", "c82"]
    assert second.target_ids == tuple(f"c{index}" for index in range(40, 80))
    ordered = [line.id for line in second.lines]
    assert ordered == sorted(ordered, key=lambda value: int(value[1:]))
    by_chars = st.plan_batches(project, None, max_items=40, max_chars=60, context_cues=0)
    assert all(batch.source_chars <= 60 for batch in by_chars)
    assert sum(len(batch.target_ids) for batch in by_chars) == 100
    sparse = st.plan_batches(project, ["c10", "c50"], context_cues=1)
    assert len(sparse) == 1
    lines = sparse[0].lines
    assert [line.id for line in lines] == ["c9", "c10", "c11", "c49", "c50", "c51"]
    assert lines[3].gap_before and not lines[1].gap_before


def test_context_lines_carry_current_translations_only():
    project = make_project()
    apply_all(project, ids=["c0", "c1"])
    cue(project, "c1").text = "ちょっと待って"
    [batch] = st.plan_batches(project, ["c2"], context_cues=2)
    context = {line.id: line.translation for line in batch.context}
    # c1's translation is stale (Japanese edited), so it is not offered.
    assert context == {"c0": "走了！", "c1": "", "c3": "", "c4": ""}


def test_messages_contract_and_traditional_target():
    project = make_project()
    [batch] = st.plan_batches(project, ["c4", "c5"], context_cues=1)
    messages = st.build_messages(batch, target="zh-Hant", game_context="艾尔登法环 Boss 战",
                                 glossary_pairs=[("ボス", "首领"), ("スライム", "史莱姆")],
                                 speaker_names={"S00": "主播"})
    system, user = messages[0]["content"], json.loads(messages[1]["content"])
    assert "繁體中文" in system and "不要合并" in system and "时间码" in system and "glossary" in system
    assert st.PROMPT_VERSION == user["prompt_version"]
    assert user["target"] == "zh-Hant" and user["output_ids"] == ["c4", "c5"]
    assert user["glossary"] == [{"ja": "ボス", "zh": "首领"}]  # only terms present in the batch
    assert user["game_context"] == "艾尔登法环 Boss 战"
    assert {line["id"] for line in user["lines"] if not line["translate"]} == {"c3", "c6"}
    provider = FakeProvider()
    result = run(project, provider, ["c4"], target="zh-Hant")
    assert "繁體中文" in provider.calls[0]["messages"][0]["content"]
    assert provider.calls[0]["kwargs"]["stage"] == st.PROVIDER_STAGE
    assert provider.calls[0]["schema"] == st.RESPONSE_SCHEMA
    st.apply_translation_result(project, result)
    assert st.records_of(project)["c4"]["target"] == "zh-Hant"
    assert st.container_target(project) == "zh-Hant"


# --- validation -------------------------------------------------------------

def batch_for(ids, texts=JA):
    project = make_project(texts)
    [batch] = st.plan_batches(project, ids, context_cues=0)
    return batch


def test_validation_reports_each_problem():
    batch = batch_for(["c0", "c1", "c2", "c3", "c4", "c5", "c7"])
    payload = {"items": [
        {"id": "c1", "translation": "等一下，我还没准备好"},          # reordered, accepted
        {"id": "c0", "translation": "走了！"},
        {"id": "c2", "translation": "糟了"}, {"id": "c2", "translation": "完了"},  # conflicting duplicate
        {"id": "c4", "translation": "このボス強すぎる"},              # Japanese echo
        {"id": "c5", "translation": "回复して！ください"},            # kana heavy
        {"id": "c7", "translation": "00:00:01,000 --> 00:00:02,000 诶"},
        {"id": "zz", "translation": "多余"},
    ]}
    accepted, problems = st.validate_response(batch, payload)
    assert accepted == {"c0": "走了！", "c1": "等一下，我还没准备好"}
    assert problems["c2"] == "duplicate_id"
    assert problems["c3"] == "missing"
    assert problems["c4"] == "echo_source"
    assert problems["c5"] == "japanese_output"
    assert problems["c7"] == "timestamp"
    assert problems["zz"] == "unknown_id"
    assert "order_mismatch" in problems[st.BATCH_PROBLEM_KEY]


@pytest.mark.parametrize("source,output,reason", [
    ("やばい", "", "empty"),
    ("やばい", "   ", "empty"),
    ("やばい", "やばい", "echo_source"),
    ("ありがとうございます", "ありがとうございます（谢谢）", "echo_source"),
    ("やばい", "やばいよね", "japanese_output"),
    ("やばい", "Oh no", "no_chinese"),
    ("やばい", "糟" * 40, "too_long"),
    ("ピカチュウ", "ピカチュウ", None),           # katakana-only name may stay
    ("期待", "期待", None),                       # kanji-only word identical in Chinese (real DeepSeek run)
    ("反省", "反省", None),
    ("ピカチュウ", "皮卡丘", None),
    ("GG", "GG", None),                          # nothing Japanese to translate
    ("えっ、何それ", "诶，那是什么？", None),
    ("マリオ行け！", "马力欧冲啊！", None),
])
def test_single_translation_validation(source, output, reason):
    assert st.validate_translation(source, output) == reason


def test_malformed_and_string_payloads():
    batch = batch_for(["c0"])
    assert st.validate_response(batch, "not json")[1]["c0"] == "malformed_response"
    accepted, _ = st.validate_response(batch, '```json\n{"items":[{"id":"c0","translation":"走了！"}]}\n```')
    assert accepted == {"c0": "走了！"}
    accepted, _ = st.validate_response(batch, {"c0": "走了！"})
    assert accepted == {"c0": "走了！"}


# --- runs: retry, failure, cancel, cache -------------------------------------

def test_partial_failure_is_retried_once_in_a_smaller_batch():
    project = make_project()

    def flaky(payload, call_no):
        items = FakeProvider.translate_all(payload, call_no)["items"]
        if call_no == 1:
            items = [item for item in items if item["id"] != "c3"]  # missing once
        return {"items": items}

    provider = FakeProvider(flaky)
    result = run(project, provider, max_items=4)
    assert not result.failed and len(result.translations) == len(JA)
    sizes = [len(call["payload"]["output_ids"]) for call in provider.calls]
    assert sizes[:2] == [4, 1] and provider.calls[1]["payload"]["output_ids"] == ["c3"]
    retry_context = {line["id"] for line in provider.calls[1]["payload"]["lines"] if not line["translate"]}
    assert {"c2", "c4"} <= retry_context
    assert result.requests == len(provider.calls)


def test_repeated_failure_marks_only_that_cue_failed():
    project = make_project()

    def stubborn(payload, call_no):
        items = FakeProvider.translate_all(payload, call_no)["items"]
        return {"items": [dict(item, translation="やばいやばい") if item["id"] == "c2" else item
                          for item in items]}

    result = run(project, FakeProvider(stubborn))
    assert set(result.failed) == {"c2"} and result.failed["c2"] == "japanese_output"
    assert len(result.translations) == len(JA) - 1
    st.apply_translation_result(project, result)
    assert st.cue_status(project, "c2") == "failed"
    assert "c2" not in project.generation_metadata["translations"]
    assert st.ids_with_status(project, {"failed"}) == ["c2"]
    # A later good run clears the failure.
    st.apply_translation_result(project, run(project, FakeProvider(), ["c2"]))
    assert st.cue_status(project, "c2") == "done"


def test_failed_retranslation_keeps_a_current_translation():
    project = make_project()
    apply_all(project)

    def broken(payload, call_no):
        return {"items": []}

    result = run(project, FakeProvider(broken), ["c2"])
    st.apply_translation_result(project, result)
    record = st.records_of(project)["c2"]
    assert st.cue_status(project, "c2") == "done" and record["last_error"] == "missing"


def test_provider_error_retries_then_fatal_error_stops():
    from twobyteasr.ai_providers import AIProviderError

    project = make_project()
    calls = []

    def transient(payload, call_no):
        calls.append(call_no)
        if call_no == 1:
            raise AIProviderError("timeout", category="timeout")
        return FakeProvider.translate_all(payload, call_no)

    waits = []
    result = st.translate(project, None, FakeProvider(transient), target="zh-Hans",
                          retry_wait=lambda seconds: waits.append(seconds) or True)
    assert not result.failed and waits == [1]

    def denied(payload, call_no):
        raise AIProviderError("401", category="authentication_required")

    provider = FakeProvider(denied)
    result = run(project, provider, max_items=3)
    assert len(provider.calls) == 1 and result.fatal_error.startswith("provider_error:authentication_required")
    assert set(result.failed) == {item.id for item in project.cues}


def test_cancellation_keeps_finished_batches():
    project = make_project()
    provider = FakeProvider()
    result = run(project, provider, max_items=3, cancel_check=lambda: len(provider.calls) >= 1)
    assert result.cancelled and result.requests == 1
    assert set(result.translations) == {"c0", "c1", "c2"}
    assert set(result.pending) == {f"c{index}" for index in range(3, 10)}
    assert provider.calls[0]["kwargs"]["cancel_check"] is not None
    st.apply_translation_result(project, result)
    assert st.ids_with_status(project, {"done"}) == ["c0", "c1", "c2"]
    assert st.cue_status(project, "c5") == "untranslated"


def test_progress_reports_counts():
    project = make_project()
    seen = []
    run(project, FakeProvider(), max_items=5, progress=lambda done, total, message: seen.append((done, total)))
    assert seen[-1] == (len(JA), len(JA))


def test_cache_hit_and_each_key_part_misses():
    project = make_project()
    cache = {}
    first = FakeProvider()
    run(project, first, cache=cache)
    assert len(cache) == len(JA) and first.calls
    again = FakeProvider()
    result = run(project, again, cache=cache)
    assert again.calls == [] and sorted(result.cache_hits) == sorted(item.id for item in project.cues)
    assert json.loads(json.dumps(cache)) == cache

    base = dict(target="zh-Hans", model="m", provider="p", glossary_digest="g")
    key = st.cache_key("やばい", ["前", "後"], **base)
    assert key == st.cache_key("やばい", ["前", "後"], **base)
    variants = [
        st.cache_key("やばいな", ["前", "後"], **base),
        st.cache_key("やばい", ["前", "别"], **base),
        st.cache_key("やばい", ["前", "後"], **{**base, "target": "zh-Hant"}),
        st.cache_key("やばい", ["前", "後"], **{**base, "model": "m2"}),
        st.cache_key("やばい", ["前", "後"], **{**base, "provider": "p2"}),
        st.cache_key("やばい", ["前", "後"], **{**base, "glossary_digest": "g2"}),
        st.cache_key("やばい", ["前", "後"], **base, prompt_version="other"),
    ]
    assert key not in variants and len(set(variants)) == len(variants)

    class OtherModel(FakeProvider):
        model = "other-model"

    other = OtherModel()
    run(project, other, ["c0"], cache=cache)
    assert other.calls  # model differs: no reuse
    glossary = FakeProvider()
    run(project, glossary, ["c0"], cache=cache, glossary_pairs=[("ボス", "首领")])
    assert glossary.calls
    hant = FakeProvider()
    run(project, hant, ["c0"], cache=cache, target="zh-Hant")
    assert hant.calls
    cue(project, "c1").text = "ちょっと待って"  # neighbour (context) changed
    neighbour = FakeProvider()
    result = run(project, neighbour, ["c0"], cache=cache)
    assert neighbour.calls and not result.cache_hits


def test_cached_entry_failing_validation_is_not_used():
    project = make_project()
    cache = {}
    run(project, FakeProvider(), ["c0"], cache=cache)
    for key in cache:
        cache[key] = {"text": "行くぞ！"}
    provider = FakeProvider()
    result = run(project, provider, ["c0"], cache=cache)
    assert provider.calls and result.translations["c0"].text == "走了！"


# --- snapshots / render view ---------------------------------------------------

def test_apply_and_restore_snapshot_round_trip():
    project = make_project()
    project.generation_metadata["translations"] = {"c0": "旧"}
    original = copy.deepcopy(project.generation_metadata)
    before, after = st.apply_translation_result(project, run(project, FakeProvider(), ["c1", "c2"]))
    assert before["translation_records"] is None and before["translations"] == {"c0": "旧"}
    assert after["translations"] == {"c0": "旧", "c1": "等一下，我还没准备好", "c2": "糟了"}
    st.restore_snapshot(project, before)
    assert project.generation_metadata == original
    st.restore_snapshot(project, after)
    assert project.generation_metadata["translation_records"] == after["translation_records"]
    assert st.cue_status(project, "c1") == "done"
    after["translations"]["c1"] = "mutated"
    assert project.generation_metadata["translations"]["c1"] != "mutated"  # deep copies


def test_render_view_sync_keeps_gone_records():
    project = make_project()
    apply_all(project, ids=["c0", "c1"])
    apply_all(project, FakeProvider(lambda payload, call_no: {"items": []}), ids=["c2"])
    assert st.cue_status(project, "c2") == "failed"
    cue(project, "c1").text = "改了"
    project.cues = [item for item in project.cues if item.id != "c0"]
    view = st.sync_render_view(project)
    assert view == {"c1": "等一下，我还没准备好"}
    assert project.generation_metadata["translations"] == view
    assert "c0" in st.records_of(project)


def test_history_is_bounded_and_previous_is_capped():
    project = make_project()
    for index in range(8):
        st.set_manual(project, "c0", f"译文{index}")
    record = st.records_of(project)["c0"]
    assert len(record["previous"]) == st.MAX_PREVIOUS and record["previous"][0]["text"] == "译文6"
    for _ in range(st.MAX_HISTORY + 5):
        st.apply_translation_result(project, run(project, FakeProvider(), ["c1"]))
    assert len(project.generation_metadata["translation_records"]["history"]) == st.MAX_HISTORY
