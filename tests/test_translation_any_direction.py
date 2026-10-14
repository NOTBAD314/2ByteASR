"""Subtitle translation in any direction (2026-10-14): sources zh/ja/en, targets
zh-Hans/zh-Hant/en/ja/ko. No network: fake provider, isolated cache."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr import subtitle_translation as st
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

ZH = ["我们先去打这个Boss", "等一下我还没准备好", "这个技能其实还挺好用的", "漂亮！"]
KO = {"我们先去打这个Boss": "먼저 이 보스부터 잡자", "等一下我还没准备好": "잠깐만 아직 준비 안 됐어",
      "这个技能其实还挺好用的": "이 스킬 사실 꽤 쓸 만해", "漂亮！": "나이스!"}


def make_project(texts=ZH, language="zh"):
    project = SubtitleProject(
        media=StudioMedia(path="synthetic.mp4", duration_ms=60_000),
        cues=[StudioCue(f"c{index}", index * 1000, index * 1000 + 900, text, speaker_id="S00")
              for index, text in enumerate(texts)],
        speakers=[StudioSpeaker("S00", "主播")],
    )
    project.validate()
    project.generation_metadata["language"] = {"code": language}
    return project


class FakeProvider:
    provider_id = "fake-provider"
    model = "fake-model"

    def __init__(self, table=KO):
        self.calls, self.table = [], table

    def structured_complete(self, messages, schema, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.calls.append({"messages": messages, "payload": payload})
        return {"items": [{"id": line["id"], "translation": self.table[line["text"]]}
                          for line in payload["lines"] if line["translate"]]}


def test_targets_are_every_other_language_of_the_source():
    assert st.targets_for("zh") == ("en", "ja", "ko")
    assert st.targets_for("ja") == ("zh-Hans", "zh-Hant", "en", "ko")
    assert st.targets_for("en") == ("zh-Hans", "zh-Hant", "ja", "ko")
    assert st.targets_for("") == st.targets_for("ja")              # projects without a record: Japanese
    assert st.same_language("zh", "zh-Hant") and not st.same_language("zh", "ko")
    for alias, target in (("KO", "ko"), ("한국어", "ko"), ("english", "en"), ("日本語", "ja"), ("zh_TW", "zh-Hant")):
        assert st.normalize_target(alias) == target
    with pytest.raises(ValueError):
        st.normalize_target("fr")


def test_chinese_targets_keep_their_prompts_and_versions():
    """Japanese/English -> Chinese records and caches stay valid."""
    assert st.prompt_version_for("ja") == st.prompt_version_for("ja", "zh-Hant") == "ja-zh-subtitle-v1"
    assert st.prompt_version_for("en", "zh-Hans") == "en-zh-subtitle-v1"
    assert st.prompt_version_for("zh", "ko") == "zh-ko-subtitle-v1"
    assert st.prompt_version_for("ja", "en") == "ja-en-subtitle-v1"
    assert st.prompt_version_for("", "ko") == "ja-ko-subtitle-v1"


def test_generic_prompt_names_the_pair_and_keys_the_glossary_by_language():
    project = make_project()
    batch = st.plan_batches(project, None)[0]
    messages = st.build_messages(batch, target="ko", glossary_pairs=[("派蒙", "파이몬"), ("技能", "스킬")],
                                 source_language="zh")
    system, payload = messages[0]["content"], json.loads(messages[1]["content"])
    assert "Chinese game live-stream" in system and "Korean" in system and "Hangul" in system
    assert payload["task"] == "Chinese subtitles -> Korean subtitles" and payload["target"] == "ko"
    assert payload["prompt_version"] == "zh-ko-subtitle-v1"
    assert payload["glossary"] == [{"zh": "技能", "ko": "스킬"}]          # only terms in this batch
    japanese = st.build_messages(batch, target="zh-Hant", source_language="ja")
    assert "日语游戏实况" in japanese[0]["content"] and "繁體" in japanese[0]["content"]


@pytest.mark.parametrize("source_language,target,source,output,reason", [
    ("zh", "en", "这个技能其实还挺好用的", "This skill is actually pretty useful", None),
    ("zh", "en", "这个技能其实还挺好用的", "这个技能其实还挺好用的", "echo_source"),
    ("zh", "en", "这个技能其实还挺好用的", "这个技能 is good", "not_english"),
    ("zh", "en", "我太喜欢原神了", "I really love 原神", None),          # a kept title
    ("zh", "ko", "这个技能其实还挺好用的", "이 스킬 사실 꽤 쓸 만해", None),
    ("zh", "ko", "这个技能其实还挺好用的", "This skill is good", "not_korean"),
    ("zh", "ko", "这个技能其实还挺好用的", "这个技能 스킬", "not_korean"),
    ("zh", "ja", "这个技能其实还挺好用的", "このスキル、実はけっこう使える", None),
    ("zh", "ja", "这个技能其实还挺好用的", "这个技能其实还挺好用的", "echo_source"),
    ("zh", "ja", "注意", "注意", None),                                  # same short kanji word
    ("zh", "ja", "我们先去打这个Boss吧", "我们先去打这个首领", "chinese_output"),
    ("ja", "ko", "このボス強すぎる", "이 보스 너무 세다", None),
    ("ja", "en", "このボス強すぎる", "This boss is way too strong", None),
    ("en", "ja", "that was a really close fight guys", "マジでギリギリの戦いだったね", None),
    ("en", "ko", "GG", "GG", None),                                     # a short token may stay
    ("en", "ko", "that was a really close fight guys", "that was a really close fight guys", "echo_source"),
    ("zh", "en", "嗯", "Mm", None),
    ("zh", "en", "？？", "??", None),
])
def test_validation_per_target_language(source_language, target, source, output, reason):
    assert st.validate_translation(source, output, target, source_language) == reason


def test_chinese_project_translates_into_korean_and_records_the_pair(tmp_path):
    project = make_project()
    provider = FakeProvider()
    result = st.translate(project, None, provider, target="ko")
    assert len(result.translations) == 4 and not result.failed
    assert result.prompt_version == "zh-ko-subtitle-v1"     # was the ja->zh version for every pair
    st.apply_translation_result(project, result)
    records = project.generation_metadata["translation_records"]
    assert records["target"] == "ko"
    assert {record["prompt_version"] for record in records["records"].values()} == {"zh-ko-subtitle-v1"}
    assert st.status_counts(project, target="ko")["done"] == 4
    assert st.status_counts(project, target="en")["needs_update"] == 4    # another target is not current

    from twobyteasr import studio_subtitle_export as export
    exported = export.export_language_layers(project, tmp_path, "实况")
    names = {artifact.layer: artifact.path.name for artifact in exported.artifacts}
    assert names == {"original": "实况.zh.srt", "translation": "实况.ko.srt", "bilingual": "实况.bilingual.srt"}
    assert "먼저 이 보스부터 잡자" in (tmp_path / "实况.ko.srt").read_text(encoding="utf-8")


def test_recognition_time_translation_runs_unless_the_target_is_the_source(monkeypatch, tmp_path):
    from twobyteasr import recognition_translation as rt
    monkeypatch.setattr(rt, "cache_path", lambda: tmp_path / "cache.json")
    cues = [SimpleNamespace(cue_id=index, start=float(index), end=index + .9, text=text, speaker="S00")
            for index, text in enumerate(ZH, 1)]
    events = []
    legacy = SimpleNamespace(record_run_event=lambda name, **kw: events.append((name, kw)),
                             add_review_item=lambda *a, **k: events.append(("review", a)))
    context = SimpleNamespace(subtitle_output="bilingual", task_language="zh", translation_script="ko",
                              game_name="", cancellation_token=None)
    added = rt.translate_runtime_cues(cues, context, legacy, provider=FakeProvider())
    assert added["translation_records"]["target"] == "ko" and len(added["translations"]) == 4
    context.translation_script = "zh-Hant"
    assert rt.translate_runtime_cues(cues, context, legacy, provider=FakeProvider()) == {}
    assert events[-1] == ("subtitle_translation_skipped", {"reason": "target_is_source_language",
                                                           "language": "zh", "target": "zh-Hant"})


def test_settings_and_run_options_accept_every_target():
    from twobyteasr.service import RunOptions
    from twobyteasr.settings import DEFAULT_SETTINGS, _merge_known_settings
    for target in st.TARGETS:
        RunOptions(translation_script=target)
        settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        settings["subtitle_language"]["translation_script"] = target
        normalized, warnings = _merge_known_settings(DEFAULT_SETTINGS, settings)
        assert normalized["subtitle_language"]["translation_script"] == target
        assert not [w for w in warnings if "translation_script" in w]
    with pytest.raises(ValueError):
        RunOptions(translation_script="fr")


def test_translation_line_falls_back_to_a_face_with_the_script():
    from twobyteasr import bilingual_layout as layout
    from twobyteasr.font_metadata import has_character
    fonts = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    assert has_character(str(fonts / "SourceHanSansSC-Medium.otf"), 0, "가")
    assert not has_character(str(fonts / "ZCOOLKuaiLe-Regular.ttf"), 0, "가")
    assert has_character(str(fonts / "ZCOOLKuaiLe-Regular.ttf"), 0, "字")
    plain = layout.BilingualSettings()
    zcool = SimpleNamespace(font_family="ZCOOL KuaiLe", font_weight=0, bold=False)
    source_han = SimpleNamespace(font_family="Source Han Sans SC", font_weight=900, bold=True)
    assert layout._translation_font(plain, "이 스킬 사실 꽤 쓸 만해", zcool) == layout.SCRIPT_FALLBACK_FONT
    assert layout._translation_font(plain, "이 스킬 사실 꽤 쓸 만해", source_han) == ""
    assert layout._translation_font(plain, "This skill is useful", zcool) == ""
    chosen = layout.BilingualSettings(translation_font="Malgun Gothic")
    assert layout._translation_font(chosen, "이 스킬", zcool) == "Malgun Gothic"   # the user's choice wins
