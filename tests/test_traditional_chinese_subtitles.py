# -*- coding: utf-8 -*-
"""字幕语言 简体中文 / 繁体中文 (2026-10-19 user request).

The home menu splits 中文 into 简体中文 and 繁体中文. Both run the same Chinese
recognition; 繁体中文 converts the delivered subtitles once, locally, before
the project is written, and the word evidence (heard in Simplified) still
times the Traditional text.
"""
from __future__ import annotations

import os
import time
import wave
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade
from twobyteasr.subtitle_rules import chinese_script
from twobyteasr.subtitle_rules.chinese_script import convert_delivered_cues, task_script, to_traditional


@pytest.mark.parametrize("simplified, traditional", [
    ("头发", "頭髮"), ("之后我们去后面", "之後我們去後面"), ("里面", "裡面"),
    ("路径", "路徑"), ("恢复", "恢復"), ("标签", "標籤"), ("一只猫", "一隻貓"),
    ("面条", "麵條"), ("这个游戏", "這個遊戲"),
])
def test_phrases_choose_the_right_traditional_character(simplified, traditional):
    assert to_traditional(simplified) == traditional


def test_wording_digits_latin_and_length_are_kept():
    text = "这个视频的质量不错，boss 打了 3 次，FPS60 稳定"
    converted = to_traditional(text)
    assert converted == "這個視頻的質量不錯，boss 打了 3 次，FPS60 穩定"   # 视频 stays 視頻, not 影片
    assert len(converted) == len(text)
    assert to_traditional(converted) == converted                        # idempotent on Traditional text
    assert to_traditional("") == ""


def test_fold_puts_both_scripts_of_a_character_together():
    fold = chinese_script.fold_map()
    key = lambda ch: fold.get(ch, ch)
    for group in ("发發髮", "后後", "里裡", "只隻", "面麵"):
        assert len({key(ch) for ch in group}) == 1, group
    assert key("我") != key("你")


def context(script="zh-Hant", language="zh"):
    return SimpleNamespace(chinese_script=script, task_language=language)


class _Legacy:
    def __init__(self):
        self.events = []

    def record_run_event(self, name, **payload):
        self.events.append((name, payload))


def cues(*texts):
    return [SimpleNamespace(cue_id=index, text=text) for index, text in enumerate(texts, 1)]


def test_only_a_chinese_task_with_traditional_chosen_is_converted():
    rows, legacy = cues("头发干了之后再说", "OK"), _Legacy()
    changed = convert_delivered_cues(rows, context(), legacy)
    assert [row.text for row in rows] == ["頭髮幹了之後再說", "OK"]
    assert [item["cue_id"] for item in changed] == [1]
    assert legacy.events[0][0] == "chinese_script_converted" and legacy.events[0][1]["cues"] == 1
    assert task_script(context()) == "zh-Hant"

    for ctx in (context("zh-Hans"), SimpleNamespace(task_language="zh")):
        rows = cues("头发")
        assert convert_delivered_cues(rows, ctx, _Legacy()) == [] and rows[0].text == "头发"
        assert task_script(ctx) == "zh-Hans"

    rows, legacy = cues("后で"), _Legacy()
    assert convert_delivered_cues(rows, context(language="ja"), legacy) == [] and rows[0].text == "后で"
    assert legacy.events == [("chinese_script_skipped", {"reason": "not_chinese", "language": "ja"})]


def test_missing_table_keeps_simplified(monkeypatch):
    monkeypatch.setattr(chinese_script, "_TABLE", ({}, {}, {}))
    rows, legacy = cues("头发"), _Legacy()
    assert convert_delivered_cues(rows, context(), legacy) == [] and rows[0].text == "头发"
    assert legacy.events[0][1]["reason"] == "table_missing"
    assert task_script(context()) == "zh-Hans"


def test_settings_and_run_options_carry_the_script():
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings
    assert DEFAULT_SETTINGS["subtitle_language"]["chinese_script"] == "zh-Hans"
    result, warnings = _merge_known_settings(DEFAULT_SETTINGS, {"subtitle_language": {
        "recognition_language": "zh", "chinese_script": "zh-Hant"}})
    assert result["subtitle_language"]["chinese_script"] == "zh-Hant"
    assert not [w for w in warnings if "subtitle_language" in w]
    result, warnings = _merge_known_settings(DEFAULT_SETTINGS, {"subtitle_language": {"chinese_script": "zh-TW"}})
    assert result["subtitle_language"]["chinese_script"] == "zh-Hans" and warnings
    with pytest.raises(ValueError):
        RunOptions(chinese_script="zh-TW")
    context = RunOptions(recognition_language="zh", chinese_script="zh-Hant").create_runtime_context(subtitle_core)
    assert context.chinese_script == "zh-Hant" and context.requested_language == "zh"


def test_traditional_cue_keeps_measured_words_from_simplified_evidence():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.subtitle_rules.sentence_refine import allocate_split_times
    heard = [("头发", 100, 400), ("干了", 450, 700), ("之后", 800, 1000), ("再说", 1100, 1400)]
    cue = StudioCue("a", 100, 1400, "頭髮幹了，之後再說", evidence_refs=["segment"])
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=3000), cues=[cue],
                              asr_evidence={"segment": {"words": [dict(text=t, start_ms=a, end_ms=b)
                                                                  for t, a, b in heard]}})
    words, reason = cue_words(project, cue)
    assert reason == "exact_token_text"
    assert [(w.text, w.char_start, w.start_ms) for w in words] == [
        ("頭髮", 0, 100), ("幹了", 2, 450), ("之後", 5, 800), ("再說", 7, 1100)]
    # The razor still cuts on the heard boundary after the comma.
    assert allocate_split_times(cue, [4], project=project) == ([(100, 700), (800, 1400)], False)


class _RunLegacy:
    """The handful of legacy hooks complete_media_run calls (see test_whitespace_recognition)."""

    def __init__(self, root):
        self.root = root
        self.events = []
        self.task_reporting = SimpleNamespace(
            report_paths_for_media=lambda path: (str(root / "report.json"), str(root / "report.txt")))

    def record_run_event(self, name, **payload):
        self.events.append((name, payload))

    @staticmethod
    def print_review_summary():
        return []

    @staticmethod
    def run_timed_stage(_index, _total, _name, _device, callback):
        return callback()

    @staticmethod
    def review_item_severity(_item):
        return "info"

    def finish_media_report(self, *_args, **kwargs):
        self.report = kwargs
        return str(self.root / "report.json"), str(self.root / "report.txt")

    @staticmethod
    def format_elapsed(seconds):
        return f"{seconds:.0f}s"


@pytest.mark.parametrize("script, expected", [
    ("zh-Hant", ["之後再說", "頭髮 乾淨了"]),
    ("zh-Hans", ["之后再说", "头发 干净了"]),
])
def test_delivered_project_and_srt_hold_the_chosen_script(tmp_path, monkeypatch, script, expected):
    import twobyteasr.projects.studio_project as storage
    from twobyteasr.exports.studio_subtitle_export import compile_srt
    from twobyteasr.recognition.pipeline_runtime import complete_media_run
    from twobyteasr.recognition.recognition_result import media_identity_for_task, verify_result_reference
    from twobyteasr.recognition.run_context import RuntimeContext
    from twobyteasr.recognition.transcript_data import SubtitleCue

    monkeypatch.setattr(storage, "project_library_root", lambda *a, **k: tmp_path / "Projects")
    real_create = storage.create_studio_outputs

    def create(media_path, cue_rows, **kwargs):
        kwargs["decoded_audio_seconds"] = None  # no media probe in this isolated test
        return real_create(media_path, cue_rows, **kwargs)

    monkeypatch.setattr(storage, "create_studio_outputs", create)
    media = tmp_path / "clip.wav"
    with wave.open(str(media), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000 * 3)
    context = RuntimeContext(media_path=str(media), job_id=f"script-{script}", chinese_script=script,
                             requested_language="zh", task_language="zh")
    context.media_identity = media_identity_for_task(media, context)
    rows = [SubtitleCue(1, 0.1, 0.9, "之后再说", speaker="S01"),
            SubtitleCue(2, 1.0, 2.0, "头发 干净了", speaker="S01")]
    complete_media_run(cues=rows, segments=[], file_index=1, file_total=1, started=time.perf_counter(),
                       audio_seconds=3.0, txt_path="", srt_path="", stage_index=1, stage_total=1,
                       legacy=_RunLegacy(tmp_path), runtime_context=context)
    project = verify_result_reference(context.committed_result_ref)
    assert [cue.text for cue in project.cues] == expected
    assert [cue.original_text for cue in project.cues] == expected
    assert project.generation_metadata["language"]["script"] == script
    reopened = storage.load_project(context.committed_result_ref["path"])
    srt = compile_srt(reopened.cues)
    assert all(line in srt for line in expected)


@pytest.fixture
def home(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, "subtitle_language",
                        {"recognition_language": "auto", "output": "original", "translation_script": "zh-Hans"})
    windows = []

    def open_window():
        win = ui.MainWindow([], subtitle_core, object(), None)
        windows.append(win)
        return win

    yield open_window
    for win in windows:
        win.close()
        win.deleteLater()
    app.processEvents()


def test_home_menu_splits_chinese_and_remembers_traditional(home):
    win = home()
    combo = win.recognition_language
    assert [combo.itemData(i) for i in range(combo.count())][:6] == ["auto", "zh", "zh-Hant", "ja", "en", "ko"]
    assert [combo.itemText(i) for i in (1, 2)] == ["简体中文", "繁体中文"]
    combo.setCurrentIndex(combo.findData("zh-Hant"))
    options = win._subtitle_language_options()
    assert (options["recognition_language"], options["chinese_script"]) == ("zh", "zh-Hant")
    saved = subtitle_core.RUNTIME_SETTINGS["subtitle_language"]
    assert (saved["recognition_language"], saved["chinese_script"]) == ("zh", "zh-Hant")
    assert "繁体中文：" in win.subtitle_language_hint.text() and not win.subtitle_language_hint.isHidden()
    # Chinese source: only non-Chinese translation targets, like 简体中文.
    targets = [win.translation_script.itemData(i) for i in range(win.translation_script.count())]
    assert "zh-Hans" not in targets and "zh-Hant" not in targets and "en" in targets
    reopened = home()
    assert reopened.recognition_language.currentData() == "zh-Hant"
    combo.setCurrentIndex(combo.findData("zh"))
    assert win._subtitle_language_options()["chinese_script"] == "zh-Hans"
    assert subtitle_core.RUNTIME_SETTINGS["subtitle_language"]["chinese_script"] == "zh-Hans"
    assert "繁体中文：" not in win.subtitle_language_hint.text()
