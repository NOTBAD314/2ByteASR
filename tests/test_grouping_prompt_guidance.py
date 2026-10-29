"""AI line-breaking prompt: built-in parts, user guidance and the Japanese copy-with-bars answer (2026-10-18)."""
import hashlib
import json

import pytest

import subtitle_core as core  # noqa: F401  (legacy core first)

from tests.test_stage9_cache_and_budget import config
from twobyteasr.subtitle_rules import grouping_request as gr

# sha256 of the prompts before the guidance became editable. Ported 2026-10-21
# onto the 0.8.2 release source (922845fe): its Chinese prompt is
# protected-boundaries-v4-source-contract (7573c026 had v3, 758dafa2…); the
# English prompt did not change.
CHINESE_BEFORE = "c09ab1e8112105954b3abd913201a837b6dd4238555d8c0d1cc609b7a5993761"
CHINESE_84_BEFORE = "18416a9d51ed4d5c5678f67cbd0ae0311412bb06671b442c25993d699acf6f9e"
ENGLISH_BEFORE = "a9fd3b02c626be738fa5b82010828c3a7aed6603d9e5c289f34372faa7c39707"
# 2026-10-21 (two-line subtitles, english-word-breaks-v2): rule 1 now allows two lines
# (84 characters, 7 s); the same text as branch claude/two-line-cues-20261021.
ENGLISH_TWO_LINE = "a582136e66fe27fba5d8d21eff762cf8854182822c7ebb2d319c104a662c7b15"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def task(monkeypatch, tmp_path):
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("fixture", "test"))

    def start(language, prompts=None):
        context = RuntimeContext(provider_snapshot=resolve_provider_snapshot(config()), task_language=language,
                                 asr_settings_snapshot={"grouping_prompts": prompts or {}},
                                 event_log_path=str(tmp_path / "events.jsonl"))
        return activate_runtime_context(context, legacy=core)
    return start


def test_built_in_chinese_and_english_prompts_are_unchanged(task):
    from twobyteasr.subtitle_rules.english_segmentation import ENGLISH_GROUPING_SYSTEM_PROMPT, build_ai_messages
    with task("zh"):
        assert sha(gr.grouping_system_prompt(core.MAX_SUBTITLE_CHARS, core.MAX_SUBTITLE_SECONDS)) == CHINESE_BEFORE
        assert gr.grouping_prompt_key("zh") == gr.GROUPING_PROMPT_VERSION
    with task("en"):
        assert sha(ENGLISH_GROUPING_SYSTEM_PROMPT) == ENGLISH_TWO_LINE
        assert sha(build_ai_messages([("1", ["hi"])])[0]["content"]) == ENGLISH_TWO_LINE
        assert gr.grouping_prompt_key("en") == gr.ENGLISH_GROUPING_PROMPT_VERSION


def test_english_on_the_boundary_protocol_keeps_the_chinese_prompt(task):
    """VibeVoice English reaches call_grouping_api (84 characters / 6 s): the
    boundary-offset prompt, never the English word-number prompt (port 2026-10-21)."""
    from twobyteasr.subtitle_rules.english_segmentation import grouping_prompt_version
    from twobyteasr.subtitle_rules.european_text import lexicon
    with task("en", {"en": "Break less often.", "zh": ""}):
        assert gr.task_prompt_language() == "zh"
        assert sha(gr.grouping_system_prompt(84, 6.0)) == CHINESE_84_BEFORE
        # The English word-break pass's cache key follows the user's English rules.
        assert grouping_prompt_version() == f"{gr.ENGLISH_GROUPING_PROMPT_VERSION}+custom-{sha('Break less often.')[:12]}"
    with task("es", {"en": "Break less often."}):
        assert grouping_prompt_version(lexicon("es")) == "es-word-breaks-v4"   # two-line subtitles (2026-10-21)


def test_user_guidance_replaces_only_the_guidance(task):
    custom = "  句末和长停顿处换句；一条最多十二个字。\n例：だから言ったじゃん｜明日は雨だって  "
    with task("ja", {"ja": custom}):
        prompt = gr.grouping_system_prompt(16, 5.0)
        key = gr.grouping_prompt_key("ja")
    head, built_in, tail = gr._japanese_parts(16, 5.0)
    assert prompt.startswith(head) and prompt.endswith(tail)
    assert custom.strip() in prompt and built_in not in prompt
    # The program-owned protocol and the hard limits survive any guidance.
    assert '"segmented_text"' in prompt and "绝对不超过16字或5.0秒" in prompt
    assert key == f"{gr.JAPANESE_GROUPING_PROMPT_VERSION}+custom-{sha(custom.strip())[:12]}"
    # Saving the built-in text unchanged, or nothing, is the built-in prompt.
    for same in ("", "   ", gr.default_grouping_guidance("ja") + "\n"):
        with task("ja", {"ja": same}):
            assert gr.grouping_system_prompt(16, 5.0) == head + built_in + tail
            assert gr.grouping_prompt_key("ja") == gr.JAPANESE_GROUPING_PROMPT_VERSION
    # Each language reads its own guidance; an overlong text is cut.
    with task("zh", {"ja": custom, "zh": "x" * (gr.CUSTOM_GUIDANCE_MAX_CHARS + 50)}):
        prompt = gr.grouping_system_prompt(16, 5.0)
        assert custom.strip() not in prompt and "x" * gr.CUSTOM_GUIDANCE_MAX_CHARS + "\n" in prompt
        assert "x" * (gr.CUSTOM_GUIDANCE_MAX_CHARS + 1) not in prompt


def test_grouped_cache_key_follows_the_prompt(task):
    import moss_firered_pipeline as pipeline
    with task("zh"):
        assert pipeline._grouping_prompt_signature(True) == {}      # existing Chinese caches stay valid
    with task("ja"):
        assert pipeline._grouping_prompt_signature(True) == {"grouping_prompt": gr.JAPANESE_GROUPING_PROMPT_VERSION}
        assert pipeline._grouping_prompt_signature(False) == {}     # local rules use no prompt
    with task("zh", {"zh": "少切一点"}):
        assert pipeline._grouping_prompt_signature(True)["grouping_prompt"].startswith(
            gr.GROUPING_PROMPT_VERSION + "+custom-")


def test_settings_keep_multi_line_guidance(tmp_path):
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings, load_runtime_settings, save_runtime_settings
    text = "第一行：句末换句。\n第二行：短句并入前后。"
    merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, {"grouping_prompts": {"ja": f"  {text}\n", "zh": 3}})
    assert merged["grouping_prompts"] == {"zh": "", "ja": text, "en": ""} and len(warnings) == 1
    save_runtime_settings({**merged}, project_root=tmp_path)
    loaded = load_runtime_settings(project_root=tmp_path)
    loaded = loaded[0] if isinstance(loaded, tuple) else loaded
    assert loaded["grouping_prompts"]["ja"] == text


def japanese_segment(text):
    return core.SpeechSegment(81, 738.13, 742.54, text, .9, [], speaker="API_S11")


def call(grouping, rows):
    from twobyteasr.recognition.run_context import get_runtime_context
    return grouping.call_grouping_api(rows, provider_snapshot=get_runtime_context().provider_snapshot)


def answer_with(monkeypatch, body):
    from twobyteasr.subtitle_rules import grouping
    records = []
    monkeypatch.setattr(grouping, "GROUPING_API_RETRIES", 1)
    monkeypatch.setattr(grouping, "post_chat_completion", lambda *a, **k: body)
    monkeypatch.setattr(grouping, "record_run_event", lambda event, **kw: records.append((event, kw)))
    return grouping, records


def test_japanese_answer_cuts_at_the_copied_bars(task, monkeypatch):
    """日常 19 batch 9: offsets 3,5,10 meant 本当だよ|本当に坂本が; the copy with bars is exact."""
    text = "本当だよ本当に坂本が入れろって言ったから"
    body = json.dumps({"segmented_text": "本当だよ| 本当に坂本が|入れろって言ったから|", "boundaries": [3, 5, 10]},
                      ensure_ascii=False)
    grouping, records = answer_with(monkeypatch, body)
    with task("ja"):
        result = call(grouping, [japanese_segment(text)])
    assert result.validated and [cue.text for cue in result] == ["本当だよ", "本当に坂本が", "入れろって言ったから"]
    trace = next(kw for event, kw in records if event == "grouping_trace")
    assert trace["final_boundaries"] == [4, 10, 20] and trace["model_boundaries"] == [4, 10, 20]
    assert next(kw for event, kw in records if event == "asr_provider_request")["prompt_version"] == \
        gr.JAPANESE_GROUPING_PROMPT_VERSION


def test_bars_win_only_for_the_japanese_prompt(task, monkeypatch):
    """The 0.8.2 contract still rejects disagreeing forms for Chinese; the Japanese
    prompt itself says the bars decide (port 2026-10-21)."""
    body = json.dumps({"segmented_text": "本当だよ|本当に坂本が入れろって言ったから", "boundaries": [3, 20]},
                      ensure_ascii=False)
    grouping, records = answer_with(monkeypatch, body)
    with task("zh"):
        result = call(grouping, [japanese_segment("本当だよ本当に坂本が入れろって言ったから")])
    assert result.origin == "fallback" and not result.validated
    assert next(kw for event, kw in records if event == "asr_provider_request")["fallback_reason"] == \
        "conflicting_representations"
    records.clear()
    with task("ja"):
        result = call(grouping, [japanese_segment("本当だよ本当に坂本が入れろって言ったから")])
    assert result.validated and [cue.text for cue in result] == ["本当だよ", "本当に坂本が入れろって言ったから"]


def test_japanese_copy_that_changes_content_is_rejected(task, monkeypatch):
    body = json.dumps({"segmented_text": "本当だよ|本当に坂本が入れたって言ったから", "boundaries": [4, 20]}, ensure_ascii=False)
    grouping, records = answer_with(monkeypatch, body)
    with task("ja"):
        result = call(grouping, [japanese_segment("本当だよ本当に坂本が入れろって言ったから")])
    assert result.origin == "fallback" and not result.validated
    assert next(kw for event, kw in records if event == "asr_provider_request")["fallback_reason"] == \
        "text_mutation_rejected"


def test_missing_closing_boundary_is_added(task, monkeypatch):
    """With fewer cuts the model sometimes stops at its last cut (…,116,122 for total 125)."""
    grouping, records = answer_with(monkeypatch, json.dumps({"boundaries": [4]}))
    with task("zh"):
        result = call(grouping, [core.SpeechSegment(1, 0, 2, "这里已经校对完成", .9, [], speaker="S01")])
    assert result.validated and "".join(cue.text for cue in result) == "这里已经校对完成"
    assert [kw["total_length"] for event, kw in records if event == "grouping_closing_boundary_added"] == [8]


def test_editor_saves_only_changed_guidance(monkeypatch):
    """The AI settings dialog's 断句提示词 editor: per-language drafts, restore, save."""
    import copy
    from PySide6.QtWidgets import QApplication
    from twobyteasr.providers.endpoint_editor_ui import PromptDialog
    from twobyteasr.storage import settings as settings_module
    _app = QApplication.instance() or QApplication([])
    saved = []
    monkeypatch.setattr(settings_module, "save_runtime_settings", lambda value: saved.append(copy.deepcopy(value)))
    settings = {"grouping_prompts": {"zh": "旧的中文说明"}, "subtitle_language": {"recognition_language": "ja"}}
    dialog = PromptDialog(None, settings)
    try:
        assert dialog._current == "ja" and dialog.editor.toPlainText() == gr.default_grouping_guidance("ja")
        assert not dialog.restore.isEnabled()
        dialog.editor.setPlainText("  句末和长停顿处换句。  ")
        assert dialog.restore.isEnabled()
        dialog.language.setCurrentIndex(dialog.language.findData("zh"))
        assert dialog.editor.toPlainText() == "旧的中文说明"
        dialog.restore.click()                                   # back to the built-in Chinese guidance
        dialog.editor.setPlainText("x" * (gr.CUSTOM_GUIDANCE_MAX_CHARS + 1))
        assert not dialog.save_button.isEnabled()
        dialog.restore.click()
        dialog.save()
    finally:
        dialog.deleteLater()
    assert saved and saved[-1]["grouping_prompts"] == {"zh": "", "ja": "句末和长停顿处换句。", "en": ""}
    assert settings["grouping_prompts"]["ja"] == "句末和长停顿处换句。"
    head, reminder, tail = gr.fixed_grouping_prompt_parts("ja")
    assert "绝对不超过16字或5.0秒" in reminder and head.startswith("你负责日语")
