"""Korean subtitles: language, text rules, line breaking (2026-10-19 user request: 字幕语言加韩语)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade
from twobyteasr.subtitle_rules import korean_segmentation as seg
from twobyteasr.subtitle_rules import korean_text as ko
from twobyteasr.subtitle_rules.language_rules import EN, JA, KO, ZH, detect_language, language_scope, \
    normalize_language, qwen_language_name, resolve_task_language, supports


def segment(segment_id, start, end, text, speaker="S00"):
    return SimpleNamespace(segment_id=segment_id, start=start, end=end, text=text, speaker=speaker, timing_locked=False)


def test_korean_is_a_task_language_and_auto_recognizes_it():
    assert normalize_language("ko") == KO and normalize_language("Korean") == KO and normalize_language("ko-KR") == KO
    assert qwen_language_name("ko") == "Korean"
    assert supports("qwen_aligner", "align", KO) and supports("moss", "transcribe", KO)
    assert not supports("firered_aed", "align", KO)
    assert detect_language(["안녕하세요 여러분 오늘도 방송 시작합니다"])[0] == KO
    assert detect_language(["오늘 Boss 잡으러 갑니다 GG"])[0] == KO
    # Chinese, Japanese and English are decided exactly as before.
    assert detect_language(["今天我们打 Boss，然后去 Mondstadt 看看风景，大家记得点赞关注"])[0] == ZH
    assert detect_language(["今日はボスを倒しに行きます、よろしくお願いします"])[0] == JA
    assert detect_language(["So today we're going to try the new boss fight, wish me luck"])[0] == EN
    assert resolve_task_language("ko", ["你好"])[0] == KO
    assert resolve_task_language("auto", ["", ""], asr_detected="Korean")[0] == KO


def test_settings_run_options_and_timeline_rule_accept_korean():
    import copy
    from twobyteasr.recognition.recognition_choices import language_timeline, spoken_language
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings
    payload = copy.deepcopy(DEFAULT_SETTINGS)
    payload["subtitle_language"]["recognition_language"] = "ko"
    merged, warnings = _merge_known_settings(DEFAULT_SETTINGS, payload)
    assert merged["subtitle_language"]["recognition_language"] == "ko"
    assert not any("subtitle_language" in warning for warning in warnings)
    assert RunOptions(recognition_language="ko", subtitle_output="bilingual").recognition_language == "ko"
    assert spoken_language(merged) == "ko"
    stage = language_timeline("local", "ko", merged)
    assert stage == {"spoken": "ko", "rerouted": True, "ctc": False, "name": "Qwen3 对齐"}


def test_korean_lengths_follow_the_netflix_counting():
    assert ko.display_length("오늘 방송") == 4.5                 # four syllables + a half-width space
    assert ko.display_length("GG 3킬") == 3.0                    # Latin, digits and the space count half
    assert ko.display_length("ㅋㅋㅋ") == 3.0
    assert ko.clean("오늘   방송 ,  시작합니다 !") == "오늘 방송, 시작합니다!"
    assert ko.word_core("방송을,") == "방송을"


def _lines(text, **kwargs):
    tokens = ko.words(text)
    return [" ".join(tokens[a:b]) for a, b in seg.split_tokens(tokens, **kwargs)]


def test_long_utterances_break_between_words_at_good_places():
    text = "안녕하세요 여러분 오늘도 방송 시작하고 있는데 이번에는 보스를 잡으러 가고 싶어요 그런 거 할 수 있어요"
    lines = _lines(text)
    assert " ".join(lines) == text                                # nothing added, lost or cut inside a word
    assert all(ko.display_length(line) <= ko.RULES.cue_max_chars for line in lines)   # two lines since 2026-10-21
    assert len(lines) >= 3
    joined = "|".join(lines)
    for pair in ("시작하고 있는데", "가고 싶어요", "할 수", "그런 거"):   # auxiliaries, dependent nouns, determiners
        assert pair in joined, (pair, lines)
    assert _lines("좋아요") == ["좋아요"]


def test_numbers_counters_and_negations_stay_together():
    text = "지금 3 개 남았는데 저는 안 해요 그리고 몇 번 더 해야 돼요 정말로"
    joined = "|".join(_lines(text))
    for pair in ("3 개", "안 해요", "몇 번"):
        assert pair in joined, joined


def test_cue_times_come_from_aligner_units_even_when_split_into_particles():
    text = "오늘 방송을 시작합니다 여러분 보스를 잡으러 가고 싶어요 같이 해 봐요 진짜로"
    units = []
    cursor = 1.0
    for word in text.split():
        # The Korean aligner splits 방송을 / 보스를 into stem + particle.
        parts = [word[:-1], word[-1]] if word.endswith(("을", "를")) else [word]
        for part in parts:
            units.append({"text": part, "start": cursor, "end": cursor + 0.2 * len(part)})
            cursor += 0.2 * len(part) + 0.05
    times = seg._word_times(segment(1, 1.0, cursor, text), text.split(), units)
    assert times[1] == (pytest.approx(units[1]["start"]), pytest.approx(units[2]["end"]))   # 방송 + 을
    cues = seg.group_korean([segment(1, 1.0, cursor, text)], units)
    assert len(cues) >= 2 and " ".join(cue.text for cue in cues) == text
    first_of_second = cues[1].text.split()[0]
    start = next(unit["start"] for unit in units if first_of_second.startswith(unit["text"]))
    assert cues[1].start == pytest.approx(start)


def test_one_coarse_aligner_unit_is_shared_between_the_words_it_covers():
    # Real clip (kuro debut, 47 s): "0715" said ten times came back as one unit;
    # every word took the whole span and five subtitles started at the same instant.
    text = "자 열 번 0715 0715 0715 0715 0715 0715"
    units = [{"text": "자", "start": 46.80, "end": 46.94}, {"text": "열", "start": 46.95, "end": 47.09},
             {"text": "번", "start": 47.09, "end": 47.23},
             {"text": "0715 0715 0715 0715 0715 0715", "start": 47.23, "end": 52.44}]
    times = seg._word_times(segment(1, 46.8, 52.44, text), text.split(), units)
    starts = [start for start, _end in times]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert times[3][0] == pytest.approx(47.23) and times[-1][1] == pytest.approx(52.44)
    cues = seg.group_korean([segment(1, 46.8, 52.44, text)], units)
    assert len({cue.start for cue in cues}) == len(cues) and all(cue.end - cue.start > 0.3 for cue in cues)


def test_ai_breaks_are_used_only_when_valid():
    text = "안녕하세요 여러분 오늘도 방송 시작하고 있는데 이번에는 보스를 잡으러 가고 싶어요"
    tokens = ko.words(text)

    def fake(answer):
        def complete(messages):
            assert "Never change, add, remove or join words" in messages[0]["content"]
            return '{"breaks": {"1": %s}}' % answer
        return complete
    assert seg.pieces_from_breaks(tokens, [0]) is None                # 여러분 … 싶어요 would be 34.5 characters
    assert seg.pieces_from_breaks(tokens, [9]) is None                # 가고 | 싶어요 cuts off the auxiliary verb
    cues = seg.group_korean_with_ai([segment(1, 0.0, 6.0, text)], complete=fake("[6]"))
    assert [cue.text for cue in cues] == [" ".join(tokens[a:b]) for a, b in ((0, 7), (7, len(tokens)))]
    # 2026-10-21: four pieces where the rules need two fall back to the rules.
    cues = seg.group_korean_with_ai([segment(1, 0.0, 6.0, text)], complete=fake("[1, 5, 7]"))
    assert [cue.text for cue in cues] == [" ".join(tokens[a:b]) for a, b in seg.split_tokens(tokens)]
    cues = seg.group_korean_with_ai([segment(1, 0.0, 6.0, text)], complete=lambda _m: "not json")
    assert " ".join(cue.text for cue in cues) == text
    assert all(ko.display_length(cue.text) <= ko.RULES.cue_max_chars for cue in cues)


def test_cleanup_inside_a_korean_task_keeps_spaces_chinese_unchanged():
    from twobyteasr.subtitle_rules.text_rules import clean_subtitle_text, content_only, normalize_output_text
    with language_scope("ko"):
        assert clean_subtitle_text("잠깐, 가지 마!  함정이야…") == "잠깐, 가지 마! 함정이야…"
        assert normalize_output_text("오늘 방송 시작") == "오늘 방송 시작"
    assert content_only("오늘 방송!") == "오늘방송"
    with language_scope("zh"):
        assert clean_subtitle_text("等一下，别走。") == "等一下别走"           # Chinese rules exactly as before


def test_korean_finalize_uses_korean_lengths():
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    from twobyteasr.recognition.transcript_data import SubtitleCue
    events = []
    legacy = SimpleNamespace(
        record_run_event=lambda name, **payload: events.append((name, payload)),
        snap_cue_starts_to_vad_onsets=lambda cues, *_a: cues,
        extend_cue_tails_by_speaker=lambda cues, *_a: cues,
        bridge_short_display_gaps=lambda cues, *_a: cues)
    cues = [SubtitleCue(1, 0.0, 0.4, "오늘 방송 시작합니다", speaker="S01"),
            SubtitleCue(2, 2.0, 3.0, "여러분 안녕하세요", speaker="S01")]
    with language_scope("ko"):
        done = finalize_cues(cues, [], [], [], 10.0, 30, legacy)
    assert [cue.text for cue in done] == ["오늘 방송 시작합니다", "여러분 안녕하세요"]      # text never changes
    assert done[0].end - done[0].start >= ko.display_length("오늘 방송 시작합니다") / ko.RULES.warning_cps - 1e-6
    assert any(name == "korean_cues_finalized" for name, _ in events)


def test_korean_translation_prompt_and_validation():
    from twobyteasr.subtitle_rules import subtitle_translation as st
    assert st.targets_for("ko") == ("zh-Hans", "zh-Hant", "en", "ja", "es", "de", "fr", "pt", "it", "ru")
    assert st.validate_translation("오늘 방송 시작합니다", "今天的直播开始了", "zh-Hans", "ko") is None
    assert st.validate_translation("오늘 방송 시작합니다", "오늘 방송 시작합니다", "zh-Hans", "ko") == "echo_source"
    assert st.validate_translation("오늘 방송 시작합니다", "오늘 방송 start", "zh-Hans", "ko") == "korean_output"
    batch = st.TranslationBatch(lines=(st.BatchLine("c1", "페이몬 진짜 시끄럽다", "", True),))
    messages = st.build_messages(batch, glossary_pairs=[("페이몬", "派蒙")], source_language="ko")
    assert "韩语游戏实况" in messages[0]["content"] and "韩语字幕 → 简体中文字幕" in messages[1]["content"]
    assert '"ko": "페이몬"' in messages[1]["content"] and st.KO_PROMPT_VERSION in messages[1]["content"]
    assert "日语游戏实况" in st.build_messages(batch)[0]["content"]                    # Japanese unchanged
    assert len({st.prompt_version_for(code) for code in ("ja", "en", "ko")}) == 3


def test_studio_refine_splits_korean_only_at_spaces():
    from twobyteasr.subtitle_rules.sentence_refine import refine_system_prompt, validate_action
    text = "오늘 방송 시작합니다, 여러분 보스 잡으러 가요"
    with language_scope("ko"):
        good = validate_action(text, {"cue_id": "1", "action": "split", "split_after_chars": [text.index(",")]})
        assert good is not None and good.action == "split"
        assert validate_action(text, {"cue_id": "1", "action": "split", "split_after_chars": [0]}) is None   # inside 오늘
        assert validate_action(text, {"cue_id": "1", "action": "space", "space_after_chars": [1]}).action == "keep"
    assert "auxiliary verb" in refine_system_prompt("ko")


def test_korean_projects_get_korean_reading_checks_and_merges():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
    from twobyteasr.timeline.studio_commands import merge_cues_command

    def project(code):
        cues = [StudioCue("a", 0, 2000, "오늘 방송 시작합니다 여러분"),
                StudioCue("b", 2000, 3000, "안녕하세요")]
        return SubtitleProject(media=StudioMedia(path="x.mp4", duration_ms=4000), cues=cues,
                               generation_metadata={"language": {"code": code}})

    korean = project("ko")
    from twobyteasr.subtitle_rules.language_rules import project_language
    assert project_language(korean) == "ko"
    flagged = {issue.issue_type for issue in SubtitleQCEngine().analyze(korean).issues if issue.cue_id == "a"}
    assert "high_cps" not in flagged                       # 13.5 characters in 2 s reads fine
    merge_cues_command(korean, ["a", "b"]).redo()
    assert korean.cues[0].text == "오늘 방송 시작합니다 여러분 안녕하세요"


def test_punctuation_and_speech_rate_know_hangul():
    from twobyteasr.forced_alignment import estimated_morae
    from twobyteasr.subtitle_rules.punctuation_style import MODE_ADD, style_text, text_language
    assert text_language("오늘 방송 시작합니다") == "ko"
    # 添加标点 adds no trailing period to Korean and leaves its word spaces alone.
    assert style_text("오늘 방송 시작합니다", MODE_ADD).text == "오늘 방송 시작합니다"
    assert style_text("今天 开始", MODE_ADD).text == "今天，开始。"                   # Chinese unchanged
    assert estimated_morae("안녕하세요") == 5.0                                     # one per syllable


@pytest.fixture
def home(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    from twobyteasr.local_models import model_workshop as workshop
    from twobyteasr.local_models.model_registry import ModelRegistry
    from twobyteasr.recognition import asr
    app = QApplication.instance() or QApplication([])
    installed = {"qwen_aligner", "firered_aed", "qwen_asr"}          # as in test_timeline_language_choice
    monkeypatch.setattr(ModelRegistry, "installed_keys", lambda self: set(installed))
    monkeypatch.setattr(ui, "installed_model_keys", lambda root: set(installed))
    monkeypatch.setattr(workshop, "_readiness_status", lambda key: "PASS")
    monkeypatch.setattr(workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr(asr, "resolve_qwen_aligner_local_source", lambda: "fixture-qwen")
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, "models", {
        **subtitle_core.RUNTIME_SETTINGS.get("models", {}),
        "primary_asr_backend": "none", "qwen_asr_backend": "local", "firered_asr_backend": "local"})
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, "subtitle_language",
                        {"recognition_language": "auto", "output": "original", "translation_script": "zh-Hans"})
    win = ui.MainWindow([], subtitle_core, object(), None)
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()


def test_home_menu_offers_korean_with_korean_chinese_bilingual(home):
    combo = home.recognition_language
    assert [combo.itemData(i) for i in range(combo.count())][:6] == ["auto", "zh", "zh-Hant", "ja", "en", "ko"]
    assert combo.itemText(combo.findData("ko")) == "韩语"
    combo.setCurrentIndex(combo.findData("ko"))
    assert subtitle_core.RUNTIME_SETTINGS["subtitle_language"]["recognition_language"] == "ko"
    options = home._subtitle_language_options()
    assert (options["recognition_language"], options["chinese_script"]) == ("ko", "zh-Hans")
    output = home.subtitle_output
    # 2026-10-21: the output choices name no language; the line under the row says it.
    # 2026-10-22: without a connected AI the item also says "（需要 API Key）" (and is greyed out).
    assert output.itemText(output.findData("bilingual")).startswith("原文 + 翻译（双语）")
    output.setCurrentIndex(output.findData("bilingual"))
    assert home.subtitle_language_summary.text() == "字幕会显示：韩语原文 + 简体中文翻译"
    output.setCurrentIndex(output.findData("original"))
    targets = [home.translation_script.itemData(i) for i in range(home.translation_script.count())]
    assert "ko" not in targets and "zh-Hans" in targets
    assert "韩语：按词断句" in home.subtitle_language_hint.text(), home.subtitle_language_hint.text()
    card = home.recognition_plan.cards["timeline"]                   # the home card names what really runs
    assert card.model_label.text() == "Qwen3 对齐"
    assert card.description_label.text() == "字幕语言是韩语，FireRedASR2-AED 只用于中文"
