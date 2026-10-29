from pathlib import Path

from twobyteasr.recognition.recognition_plans import (
    lightweight_media_profile,
    matching_plan,
    recognition_plan,
)


def test_quality_plan_maps_to_independent_primary_timeline_and_review():
    plan = recognition_plan("quality")
    assert (plan.primary, plan.timeline, plan.review) == ("moss", "local", "local")
    assert matching_plan("moss", "local", "local") == "quality"


def test_unknown_backend_combination_is_custom():
    assert matching_plan("firered_llm", "qwen_aligner", "api") == "custom"
    assert recognition_plan("stale-setting").key == "custom"


def test_lightweight_profile_recommends_quality_or_cloud_without_gpu(tmp_path):
    # 2026-10-22: 速度优先 / 省显存 were removed; without a GPU the cloud plan
    # is the light first pass.
    audio = Path(tmp_path) / "sample.wav"
    audio.write_bytes(b"0" * 1024)
    profile = lightweight_media_profile([audio])
    assert profile["audio_only"] is True
    assert profile["recommended_plan"] == "quality"
    assert lightweight_media_profile([audio], has_gpu=False)["recommended_plan"] == "moss_pro_qwen"
    assert lightweight_media_profile([])["recommended_plan"] == "quality"


def test_menu_is_local_api_japanese_foreign_and_api_times_by_language():
    # 2026-10-23 (user): 本地识别 / API 转写 / 日语 / 外语 only; 自定义 is a state.
    from twobyteasr.recognition.recognition_choices import HostProfile
    from twobyteasr.recognition.recognition_plans import REMOVED_PLANS, plan_options
    plans = plan_options()
    assert [(plan.key, plan.label) for plan in plans] == [
        ("quality", "本地识别"), ("moss_pro_qwen", "API 转写"), ("japanese", "日语"), ("english", "外语")]
    assert not REMOVED_PLANS & {plan.key for plan in plans}
    assert recognition_plan("api").key == "custom"
    cloud = recognition_plan("moss_pro_qwen")
    assert (cloud.primary, cloud.review, cloud.api_provider) == ("api", "off", "mosi_moss_pro")
    # MOSS Pro + FireRedASR2 for Chinese / auto, Qwen3 对齐 for other languages.
    assert cloud.backends("zh") == ("api", "local", "off")
    assert cloud.backends("auto") == ("api", "local", "off")
    for language in ("en", "ja", "ko", "de"):
        assert cloud.backends(language) == ("api", "qwen_aligner", "off")
    # FireRedASR2 needs an NVIDIA GPU; without one the plan uses Qwen3 对齐.
    no_gpu = HostProfile("win32", "amd64", False, True, False, True)
    assert cloud.backends("zh", no_gpu) == ("api", "qwen_aligner", "off")
    for timeline in ("local", "qwen_aligner"):
        assert matching_plan("api", timeline, "off") == "moss_pro_qwen"
        assert matching_plan("api", timeline, "off", "en", provider="mosi_moss_pro") == "moss_pro_qwen"
    assert matching_plan("api", "qwen_aligner", "off", provider="groq") == "custom"
    assert matching_plan("api", "off", "api") == "custom"


def test_language_presets_use_moss_aligner_and_qwen_review_for_their_language():
    # 2026-10-14: 日语 = MOSS + Qwen3 aligner (CTC starts) + Qwen3-ASR 1.7B;
    # 外语 (2026-10-23: was 英语推荐) = the same with Qwen3-ForcedAligner 0.6B
    # word times, for every language other than Chinese and Japanese.
    from twobyteasr.recognition.recognition_plans import FOREIGN
    japanese, english = recognition_plan("japanese"), recognition_plan("english")
    assert (japanese.primary, japanese.timeline, japanese.review, japanese.language) == ("moss", "qwen_aligner", "local", "ja")
    assert (english.primary, english.timeline, english.review, english.language) == ("moss", "qwen_aligner", "local", FOREIGN)
    assert matching_plan("moss", "qwen_aligner", "local", "ja") == "japanese"
    for language in ("en", "ko", "es", "ru"):
        assert matching_plan("moss", "qwen_aligner", "local", language) == "english"
    # Chinese or unknown language with the same backends is not called a language preset.
    assert matching_plan("moss", "qwen_aligner", "local", "zh") == "custom"
    assert matching_plan("moss", "qwen_aligner", "local") == "custom"
    assert matching_plan("moss", "local", "local", "ja") == "quality"
