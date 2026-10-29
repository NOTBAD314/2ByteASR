"""Math formulas in AI text features + the user's note to AI per term library (2026-10-16, ADR 0124 stage 1B).

With the project's math switch on, AI 校对 / AI 清理 / 字幕翻译 never see a `$…$` formula, only ⟦Fn⟧
placeholders, and formulas come back unchanged or the subtitle keeps its text; AI 断句 never cuts inside
a formula. A library's note to AI reaches the correction prompt only when one is written.
"""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# Like the app and the review service: subtitle_core first, so polishing's star import is complete
# (importing text_rules first loads polishing while subtitle_core is still initializing).
import subtitle_core  # noqa: F401
from twobyteasr.glossary.terminology import (GlossaryLibrary, GlossarySnapshot, TermEntry, glossary_ai_notes,
                                             library_ai_note)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.subtitle_rules import math_text
from twobyteasr.subtitle_rules.math_text import FORMULA_RULE, mask_formulas, unmask_formulas

FORMULA = r"$\frac{\sqrt{3}}{4}a^2$"


def make_project(*texts, math=True):
    project = SubtitleProject(media=StudioMedia(path="isolated.mp4"), glossary_ids=["v"],
                              cues=[StudioCue(str(i), i * 2000, i * 2000 + 1000, text, original_text=text,
                                              speaker_id="S01") for i, text in enumerate(texts, 1)])
    if math:
        project.studio_state[math_text.STATE_KEY] = math_text.state_value(True)
    project.validate()
    return project


def library(note=""):
    profile = {"_content_domain": {"id": "v", "name": "数学", "source": "saved_library_game"}}
    if note:
        profile["_ai_note"] = note
    return GlossarySnapshot((GlossaryLibrary("v", "数学", "1", terms=(TermEntry("谢尔宾斯基", category="名词"),),
                                             profile_json=json.dumps(profile, ensure_ascii=False)),))


# ---------------------------------------------------------------- placeholders

def test_mask_and_unmask_round_trip_and_refuse_broken_answers():
    masked, formulas = mask_formulas(f"面积是 {FORMULA}，而 $x$ 是边长，门票 \\$5")
    assert masked == "面积是 ⟦F1⟧，而 ⟦F2⟧ 是边长，门票 \\$5" and formulas == (FORMULA, "$x$")
    assert unmask_formulas(masked, formulas) == f"面积是 {FORMULA}，而 $x$ 是边长，门票 \\$5"
    assert unmask_formulas("面积 ⟦F2⟧ 和 ⟦F1⟧", formulas) == f"面积 $x$ 和 {FORMULA}"  # moved: allowed
    for broken in ("面积是 ⟦F1⟧", "⟦F1⟧⟦F1⟧⟦F2⟧", "⟦F1⟧⟦F2⟧⟦F3⟧", "⟦F1⟧ ⟦F 2⟧"):
        assert unmask_formulas(broken, formulas) is None
    assert unmask_formulas("没有公式", ()) == "没有公式"


def test_placeholders_survive_the_correction_text_cleanup():
    from twobyteasr.subtitle_rules.text_rules import clean_subtitle_text
    assert "⟦F1⟧" in clean_subtitle_text("面积是 ⟦F1⟧，对吧。") and "⟦F12⟧" in clean_subtitle_text("还有⟦F12⟧")


# ---------------------------------------------------------------- correction prompt

def correction_messages(text, snapshot):
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.transcript_data import SpeechSegment
    from twobyteasr.subtitle_rules import polishing
    row = SpeechSegment(1, 0, 1, text, .9, [], speaker="S01", primary_source="project-original")
    context = RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=["v"], glossary_snapshot=snapshot)
    with activate_runtime_context(context):
        return polishing.call_correction_api([row], [], "", "", "合成夹具", "", [], [], [],
                                             glossary_evidence=snapshot.evidence(), _messages_only=True)


def test_prompt_additions_appear_only_when_they_apply():
    from twobyteasr.subtitle_rules.polishing import USER_GLOSSARY_NOTES_RULE
    plain = correction_messages("谢尔宾斯基三角形", library())[0]["content"]
    assert FORMULA_RULE not in plain and USER_GLOSSARY_NOTES_RULE not in plain
    with_formula = correction_messages("面积是 ⟦F1⟧", library())[0]["content"]
    assert with_formula == plain + "\n" + FORMULA_RULE
    note = "这是数学科普，$…$ 是公式，保持原样。"
    with_note = correction_messages("谢尔宾斯基三角形", library(note))[0]["content"]
    assert with_note == plain + "\n" + USER_GLOSSARY_NOTES_RULE + "\n【数学】" + note


def test_snapshot_carries_the_note_without_touching_libraries_that_have_none(monkeypatch):
    from twobyteasr.glossary.terminology import snapshot_glossaries
    games = {"v": {"game": "数学", "library_id": "v", "mappings": []},
             "w": {"game": "游戏", "library_id": "w", "mappings": [], "ai_note": "选手名按词库统一。"}}
    legacy = SimpleNamespace(load_learned_term_payload=lambda: {"games": games})
    snapshot = snapshot_glossaries(legacy, ["v", "w"])
    assert [library_ai_note(x) for x in snapshot.libraries] == ["", "选手名按词库统一。"]
    assert "_ai_note" not in snapshot.libraries[0].profile_json
    assert glossary_ai_notes(snapshot) == [("游戏", "选手名按词库统一。")]
    restored = GlossarySnapshot.from_dict(snapshot.to_dict())
    assert restored.digest == snapshot.digest and glossary_ai_notes(restored) == glossary_ai_notes(snapshot)


def test_note_is_saved_cleared_and_also_works_for_a_builtin_library():
    import subtitle_core
    assert subtitle_core.create_learned_content("数学测试库")
    library_id = subtitle_core.resolve_glossary_identity("数学测试库")
    assert subtitle_core.set_learned_content_note("数学测试库", library_id, "  公式保持原样。\r\n人名统一。 ")
    assert subtitle_core.learned_content_note(library_id) == "公式保持原样。\n人名统一。"
    assert subtitle_core.set_learned_content_note("数学测试库", library_id, "x" * 5000)
    assert len(subtitle_core.learned_content_note(library_id)) == 1000
    assert subtitle_core.set_learned_content_note("数学测试库", library_id, "")
    assert subtitle_core.learned_content_note(library_id) == ""
    assert "ai_note" not in subtitle_core.load_learned_term_payload()["games"][library_id]
    # A library known only from the built-in profiles: the first note creates its personal entry.
    assert subtitle_core.set_learned_content_note("示例内置库", "builtin-example", "按官方译名统一。")
    assert subtitle_core.learned_content_note("builtin-example") == "按官方译名统一。"


# ---------------------------------------------------------------- AI 校对

def fake_model(monkeypatch, answer):
    import twobyteasr.providers.asr_provider_snapshot as provider
    import twobyteasr.subtitle_rules.polishing as polish
    seen = []
    monkeypatch.setattr(provider, "resolve_provider_snapshot", lambda *_a, **_kw: SimpleNamespace(
        public_identity=lambda: {"provider": "offline-test", "model": "offline-test"},
        timeout_policy=SimpleNamespace(total=10)))

    def call(rows, *_args, **kwargs):
        if kwargs.get("_messages_only"):  # the service prepares the next batch ahead of time
            return []
        seen.extend(row.text for row in rows)
        return polish.PolishBatchResult({row.segment_id: answer(row.text) for row in rows})
    monkeypatch.setattr(polish, "call_correction_api", call)
    return seen


def test_review_never_sends_a_formula_and_keeps_it(monkeypatch):
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    from twobyteasr.studio.studio_text_tools import values_from_occurrences
    seen = fake_model(monkeypatch, lambda text: text.replace("谢尔宾斯机", "谢尔宾斯基"))
    project = make_project(f"谢尔宾斯机三角形的面积是 {FORMULA}")
    result = preview_glossary_correction(project, ["1"], library(), {})
    assert seen == ["谢尔宾斯机三角形的面积是 ⟦F1⟧"]
    assert values_from_occurrences(project, result.hits) == {"1": f"谢尔宾斯基三角形的面积是 {FORMULA}"}
    assert "formula_rejected_cues" not in result.receipt


def test_review_answer_that_breaks_a_formula_changes_nothing(monkeypatch):
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    fake_model(monkeypatch, lambda text: text.replace("⟦F1⟧", "三分之根号三").replace("谢尔宾斯机", "谢尔宾斯基"))
    project = make_project(f"谢尔宾斯机三角形的面积是 {FORMULA}")
    result = preview_glossary_correction(project, ["1"], library(), {})
    assert not [hit for hit in result.hits if hit.source == "ai_accepted"]
    assert result.receipt["formula_rejected_cues"] == ["1"]


def test_review_with_the_switch_off_sends_the_text_as_before(monkeypatch):
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    seen = fake_model(monkeypatch, lambda text: text)
    preview_glossary_correction(make_project(f"面积是 {FORMULA}", math=False), ["1"], library(), {})
    assert seen == [f"面积是 {FORMULA}"]


# ---------------------------------------------------------------- AI 清理

@pytest.mark.parametrize("answer, expected", [
    ("面积就是 ⟦F1⟧", {"1": f"面积就是 {FORMULA}"}),
    ("面积就是三分之根号三", {}),
])
def test_cleanup_masks_and_drops_broken_suggestions(monkeypatch, answer, expected):
    import twobyteasr.providers.ai_providers as providers
    from twobyteasr.studio.studio_text_tools import request_text_cleanup, values_from_occurrences
    calls = []

    class Provider:
        def complete(self, messages, **_kwargs):
            calls.append(messages)
            return json.dumps({"changes": [{"cue_id": "1", "original": "嗯嗯面积就是 ⟦F1⟧", "replacement": answer,
                                            "reason": "口癖", "confidence": .9}]})
    monkeypatch.setattr(providers, "provider_for_stage", lambda *_a, **_kw: Provider())
    project = make_project(f"嗯嗯面积就是 {FORMULA}")
    hits = request_text_cleanup(project, ["1"], ["fillers"], {"models": {"polish": {}}})
    payload = json.loads(calls[0][1]["content"])
    assert payload["cues"] == [{"cue_id": "1", "text": "嗯嗯面积就是 ⟦F1⟧"}] and FORMULA_RULE in calls[0][0]["content"]
    assert values_from_occurrences(project, hits) == expected


# ---------------------------------------------------------------- AI 断句

def test_sentence_refine_never_cuts_inside_a_formula(monkeypatch):
    import twobyteasr.providers.ai_providers as providers
    from twobyteasr.subtitle_rules.sentence_refine import _refine_cues
    text = "面积是 $\\frac{a}{b}$ 对吧"
    inside = text.index("frac")  # a cut after this index lands inside the formula
    outside = text.index("$ 对") + 1
    answers = [json.dumps({"results": [{"cue_id": "1", "action": "split", "split_after_chars": [inside]},
                                       {"cue_id": "2", "action": "split", "split_after_chars": [outside]}]})]

    class Provider:
        def complete(self, messages, **_kwargs):
            return answers.pop(0)
    project = make_project(text, text)
    outcome = _refine_cues(project.cues, project, Provider(), None, 10, 1, "zh")
    actions = {action.cue_id: action.action for action in outcome.actions}
    assert actions["1"] == "keep"
    assert any(row.get("category") == "cut_inside_formula" for row in outcome.requests[0].get("field_errors", ()))


# ---------------------------------------------------------------- 字幕翻译

def test_translation_round_trips_formulas_and_retries_a_lost_one():
    from twobyteasr.subtitle_rules.subtitle_translation import translate, translation_source
    project = make_project(f"面积是 {FORMULA}")
    project.generation_metadata["language"] = {"code": "zh"}
    calls = []

    class Provider:
        provider_id, model = "fake", "fake"

        def structured_complete(self, messages, schema, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            calls.append((messages[0]["content"], payload))
            line = payload["lines"][0]
            text = "The area is ⟦F1⟧" if len(calls) > 1 else "The area is root three over four"
            return {"items": [{"id": line["id"], "translation": text}]}
    source = translation_source(project)
    assert source.math_formulas
    result = translate(source, None, Provider(), target="en")
    assert calls[0][1]["lines"][0]["text"] == "面积是 ⟦F1⟧" and FORMULA_RULE in calls[0][0]
    assert {"id": "1", "reason": "formula_lost", "batch": 1} in result.problems
    assert result.translations["1"].text == f"The area is {FORMULA}"
