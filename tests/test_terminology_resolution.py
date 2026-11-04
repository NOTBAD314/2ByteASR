"""Confirmed terminology executes without AI and without leaking other libraries."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.glossary.terminology import TermResolver, apply_to_segments, snapshot_glossaries


def facade(mappings, other=()):
    games = {
        "valorant-id": {"game": "瓦罗兰特", "library_id": "valorant-id", "revision": 3,
                        "mappings": mappings},
        "other-id": {"game": "其他", "mappings": list(other)},
    }
    return SimpleNamespace(load_game_profiles=lambda: {},
        load_learned_term_payload=lambda: deepcopy({"games": games}),
        runtime_game_identity=lambda x: x.casefold(),
        resolve_glossary_identity=lambda x: x,
        games=games)


def confirmed(source, target):
    return {"from": source, "to": target, "confirmed": True,
            "provenance": "user_confirmed", "origin": "手动"}


def resolver(*rows):
    return TermResolver(snapshot_glossaries(facade(list(rows)), ["valorant-id"]))


def test_case_spelling_confirmed_alias_and_cjk_ascii_boundaries():
    terms = resolver(confirmed("BerLIN", "BerLIN"), confirmed("Borlin", "BerLIN"),
                     confirmed("S0PP", "S0PP"))
    result = terms.resolve("berlin也没有接住 BORLIN也没有接住 s0pp S0pp sopp SOPP xberlin berlin2 _berlin")
    assert result.text == "BerLIN也没有接住 BerLIN也没有接住 S0PP S0PP sopp SOPP xberlin berlin2 _berlin"
    assert len(result.hits) == 4
    assert terms.resolve(result.text).text == result.text


def test_zero_letter_alias_requires_confirmation_and_other_library_does_not_leak():
    legacy = facade([confirmed("S0PP", "S0PP"),
                     {"from": "sopp", "to": "S0PP", "confirmed": False,
                      "provenance": "candidate"}], [confirmed("berlin", "BerLIN")])
    terms = TermResolver(snapshot_glossaries(legacy, ["valorant-id"]))
    assert terms.resolve("sopp berlin s0pp").text == "sopp berlin S0PP"
    legacy.games["valorant-id"]["mappings"].append(confirmed("sopp", "S0PP"))
    assert TermResolver(snapshot_glossaries(legacy, ["valorant-id"])).resolve("SOPP").text == "S0PP"
    assert terms.resolve("SOPP").text == "SOPP"


def test_literals_longest_match_and_conflicts_are_stable_across_loading_order():
    rows = [confirmed("a+b", "A+B"), confirmed("a", "A"),
            confirmed("wrong", "One"), confirmed("wrong", "Two")]
    terms = resolver(*rows)
    result = terms.resolve("a+b也 a ax wrong也")
    assert result.text == "A+B也 A ax wrong也"
    assert any(x.reason == "ambiguous_mapping" for x in result.conflicts)
    assert any(x.reason == "ambiguous_mapping" for x in result.skipped)
    assert resolver(*reversed(rows)).resolve("a+b也 a ax wrong也").text == result.text


@pytest.mark.parametrize("rows", [
    [confirmed("A", "B"), confirmed("B", "C")],
    [confirmed("A", "B"), confirmed("B", "A")],
])
def test_chains_cycles_and_repeat_application_are_idempotent(rows):
    terms = resolver(*rows)
    once = terms.resolve("A B C也").text
    assert terms.resolve(once).text == once
    assert terms.conflicts


def test_snapshot_is_immutable_and_records_revision_and_content_digest():
    legacy = facade([confirmed("berlin", "BerLIN")])
    frozen = snapshot_glossaries(legacy, ["valorant-id"])
    original = frozen.to_dict()
    legacy.games["valorant-id"]["game"] = "改名"
    legacy.games["valorant-id"]["revision"] = 4
    legacy.games["valorant-id"]["mappings"][0]["to"] = "Different"
    assert frozen.to_dict() == original
    assert frozen.libraries[0].id == "valorant-id"
    assert frozen.libraries[0].revision == "3"
    assert snapshot_glossaries(legacy, ["valorant-id"]).digest != frozen.digest
    assert TermResolver(frozen).resolve("berlin也").text == "BerLIN也"


def test_adjacent_replacements_cannot_generate_a_second_pass_alias():
    terms = resolver(confirmed("甲", "B"), confirmed("乙", "B"), confirmed("BB", "C"))
    result = terms.resolve("甲乙")
    assert terms.resolve(result.text).text == result.text
    assert result.text == "甲乙"
    assert any(x.reason == "non_idempotent_combination" for x in result.skipped)


def test_segment_case_only_keeps_word_times_and_length_change_remaps_whole_span():
    frozen = snapshot_glossaries(facade([confirmed("BerLIN", "BerLIN"),
        confirmed("Borl", "BerLIN")]), ["valorant-id"])
    first = SpeechSegment(1, 1.0, 3.0, "berlin也", .9,
        [WordUnit(1.0, 2.0, "berlin", .9), WordUnit(2.0, 3.0, "也", .9)], speaker="S03")
    second = SpeechSegment(2, 3.0, 5.0, "Borl也", .9,
        [WordUnit(3.0, 4.0, "Borl", .9), WordUnit(4.0, 5.0, "也", .9)], speaker="S04")
    apply_to_segments([first, second], frozen)
    assert first.text == first.final_text == "BerLIN也"
    assert [(w.start, w.end) for w in first.words] == [(1., 2.), (2., 3.)]
    assert [w.text for w in first.words] == ["BerLIN", "也"]
    assert second.text == second.final_text == "BerLIN也"
    assert "".join(w.text for w in second.words) == second.text
    assert [(w.start, w.end) for w in second.words] == [(3., 4.), (4., 5.)]
    assert (first.start, first.end, first.speaker) == (1., 3., "S03")
    assert (second.start, second.end, second.speaker) == (3., 5., "S04")
    assert second.caption_arbitration["terminology_normalization"][-1]["timing"] == "existing-word-spans"


def test_run_options_pin_actual_content_before_later_edits_and_apply():
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.recognition.run_context import activate_runtime_context
    legacy = facade([confirmed("Borlin", "BerLIN")])
    options = RunOptions(enable_domain_terms=True, enabled_glossary_ids=("valorant-id",))
    context = options.create_runtime_context(legacy)
    legacy.games["valorant-id"]["mappings"][0]["to"] = "Different"
    options.apply(legacy, context)
    assert TermResolver(context.glossary_snapshot).resolve("Borlin也").text == "BerLIN也"
    assert context.glossary_snapshot.summary()["libraries"][0]["revision"] == "3"
    with activate_runtime_context(context):
        import subtitle_core
        assert subtitle_core.learned_canonical_terms() == ["BerLIN"]
        assert subtitle_core.enabled_glossary_adjudication_evidence()["canonical_terms"] == ["BerLIN"]


def test_production_local_grouping_timing_and_outputs_share_final_spelling(tmp_path):
    import subtitle_core as legacy
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.subtitle_rules.output import render_srt, render_txt
    snapshot = snapshot_glossaries(facade([confirmed("Borlin", "BerLIN"),
        confirmed("S0PP", "S0PP")]), ["valorant-id"])
    segments = [SpeechSegment(1, 0., 3., "Borlin也没有接住", .9,
        [WordUnit(0., 1., "Borlin", .9), WordUnit(1., 3., "也没有接住", .9)], speaker="S03")]
    context = RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=["valorant-id"],
        glossary_snapshot=snapshot)
    with activate_runtime_context(context, legacy=legacy):
        apply_to_segments(segments, snapshot, legacy)
        segments = legacy.apply_editorial_segment_rules(segments)
        apply_to_segments(segments, snapshot, legacy)
        cues = legacy.group_subtitles(segments, use_ai=False)
        cues = finalize_cues(cues, segments, [], [], 3., 30., legacy)
        assert "".join(cue.text.replace(" ", "") for cue in cues) == "BerLIN也没有接住"
        assert {cue.speaker for cue in cues} == {"S03"}
        (tmp_path / "result.srt").write_text(render_srt(cues), encoding="utf-8-sig")
        (tmp_path / "result.txt").write_text(render_txt(cues), encoding="utf-8-sig")
    assert "BerLIN" in (tmp_path / "result.srt").read_text(encoding="utf-8-sig")
    assert "BerLIN" in (tmp_path / "result.txt").read_text(encoding="utf-8-sig")


def test_supported_qwen_context_uses_pinned_spelling_and_frozen_worker_manifest(tmp_path, monkeypatch):
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    import json
    import sys
    snapshot = snapshot_glossaries(facade([confirmed("Borlin", "BerLIN"),
        confirmed("S0PP", "S0PP")]), ["valorant-id"])
    context = RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=["valorant-id"],
        glossary_snapshot=snapshot)
    (tmp_path / "qwen_asr_worker.py").write_text("# worker fixture", encoding="utf-8")
    monkeypatch.setattr(asr, "SCRIPT_DIR", str(tmp_path))
    monkeypatch.setattr(asr, "_main_worker_python", lambda: sys.executable)
    monkeypatch.setattr(asr, "write_pcm16_wav", lambda *args: None)
    captured = []
    def worker(command, *args, **kwargs):
        captured.append(json.loads(__import__("pathlib").Path(command[command.index('--manifest')+1]).read_text(encoding="utf-8")))
        return {"results": [{"text": "BerLIN", "confidence": .9}]}
    monkeypatch.setattr(asr, "_run_isolated_asr_worker", worker)
    with activate_runtime_context(context):
        prompt = asr.build_qwen_asr_context("clip.mp4")
        assert "BerLIN" in prompt and "S0PP" in prompt
        assert "不得补写未说内容" in prompt
        asr._transcribe_qwen_worker(None, [{"audio": ([0.0], 16000), "start": 0., "end": 1.}], "fixture")
    assert "BerLIN" in captured[0]["jobs"][0]["context"]
    assert "S0PP" in captured[0]["jobs"][0]["context"]


def test_actual_queue_logs_loaded_snapshot_and_uses_it_after_library_edit(tmp_path):
    import json
    from pathlib import Path
    from tests.test_service_layer import FakeLegacy, FakePipeline
    from twobyteasr.recognition.service import RunOptions, run_media_queue
    legacy = FakeLegacy(tmp_path)
    storage = facade([confirmed("Borlin", "BerLIN")])
    legacy.load_learned_term_payload = storage.load_learned_term_payload
    legacy.load_game_profiles = storage.load_game_profiles
    options = RunOptions(enable_domain_terms=True, enabled_glossary_ids=("valorant-id",),
        glossary_snapshot_json=json.dumps(snapshot_glossaries(storage, ["valorant-id"]).to_dict()))
    storage.games["valorant-id"]["mappings"][0]["to"] = "Different"
    class Pipeline(FakePipeline):
        def process_media(self, path, index, count, owner, runtime_context=None):
            assert TermResolver(runtime_context.glossary_snapshot).resolve("Borlin也").text == "BerLIN也"
            return super().process_media(path, index, count, owner)
    path = tmp_path / "isolated.wav"; path.write_bytes(b"fixture")
    events = []
    result = run_media_queue([str(path)], options, events.append, _legacy=legacy,
        _pipeline=Pipeline(), _skip_environment_preflight=True)
    assert result.results[0].status == "success"
    loaded = next(x.payload for x in events if x.kind == "terminology_snapshot_loaded")
    assert loaded["libraries"][0] == {"id": "valorant-id", "name": "瓦罗兰特", "revision": "3",
        "found": True, "confirmed_terms": 1, "reference_terms": 0}
    assert loaded["effective_terms"] == 1


def test_disabled_task_cannot_consume_stale_selected_snapshot():
    import json
    from twobyteasr.recognition.service import RunOptions
    storage = facade([confirmed("Borlin", "BerLIN")])
    options = RunOptions(enable_domain_terms=False, enabled_glossary_ids=("valorant-id",),
        glossary_snapshot_json=json.dumps(snapshot_glossaries(storage, ["valorant-id"]).to_dict()))
    context = options.create_runtime_context(storage)
    assert not context.enable_domain_terms
    assert context.enabled_glossary_ids == []
    assert context.glossary_snapshot.canonical_terms == ()


def test_fuzzy_dictionary_match_is_review_candidate_without_confirmed_alias():
    import subtitle_core as legacy
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    snapshot = snapshot_glossaries(facade([confirmed("BerLIN", "BerLIN")]), ["valorant-id"])
    segment = SpeechSegment(1, 0., 2., "阿辉也没接住", .9, [], firered_text="阿晖也没接住")
    context = RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=["valorant-id"],
        glossary_snapshot=snapshot)
    with activate_runtime_context(context, legacy=legacy):
        legacy.repair_with_verified_game_terms([segment], ["阿晖"])
    assert segment.text == "阿辉也没接住"
    assert any(item["category"] == "术语候选" and "需确认" in item["detail"] for item in context.review_items)
