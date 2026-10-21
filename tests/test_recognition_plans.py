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


def test_lightweight_profile_recommends_speed_for_small_audio(tmp_path):
    audio = Path(tmp_path) / "sample.wav"
    audio.write_bytes(b"0" * 1024)
    profile = lightweight_media_profile([audio])
    assert profile["audio_only"] is True
    assert profile["recommended_plan"] == "speed"


def test_lightweight_profile_recommends_low_memory_for_large_batch(tmp_path):
    paths = []
    for index in range(5):
        path = Path(tmp_path) / f"sample-{index}.mp4"
        path.write_bytes(b"0")
        paths.append(path)
    assert lightweight_media_profile(paths)["recommended_plan"] == "low_memory"


def test_language_presets_use_moss_aligner_and_qwen_review_for_their_language():
    # 2026-10-14: 日语推荐 = MOSS + Qwen3 aligner (CTC starts) + Qwen3-ASR 1.7B;
    # 英语推荐 = the same with Qwen3-ForcedAligner 0.6B word times.
    japanese, english = recognition_plan("japanese"), recognition_plan("english")
    assert (japanese.primary, japanese.timeline, japanese.review, japanese.language) == ("moss", "qwen_aligner", "local", "ja")
    assert (english.primary, english.timeline, english.review, english.language) == ("moss", "qwen_aligner", "local", "en")
    assert matching_plan("moss", "qwen_aligner", "local", "ja") == "japanese"
    assert matching_plan("moss", "qwen_aligner", "local", "en") == "english"
    # Chinese or unknown language with the same backends is not called a language preset.
    assert matching_plan("moss", "qwen_aligner", "local", "zh") == "custom"
    assert matching_plan("moss", "qwen_aligner", "local") == "custom"
    assert matching_plan("moss", "local", "local", "ja") == "quality"
