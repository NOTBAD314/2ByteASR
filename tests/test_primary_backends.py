import numpy as np
import pytest

from twobyteasr.hardware import combination_requires_cuda, selected_cuda_components
from twobyteasr.settings import DEFAULT_SETTINGS, _merge_known_settings


@pytest.mark.parametrize(
    ("primary", "review"),
    [
        ("moss", "local"),
        ("firered_llm", "local"),
        ("qwen_local", "firered_llm"),
    ],
)
def test_verified_primary_review_combinations_survive_settings_validation(
    primary, review
):
    settings, warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {
            "models": {
                "primary_asr_backend": primary,
                "qwen_asr_backend": review,
            }
        },
    )

    assert settings["models"]["primary_asr_backend"] == primary
    assert settings["models"]["qwen_asr_backend"] == review
    assert not [
        item
        for item in warnings
        if "primary_asr_backend" in item or "qwen_asr_backend" in item
    ]


def test_primary_backend_validation_and_backward_default():
    settings, warnings = _merge_known_settings(DEFAULT_SETTINGS, {"models": {}})
    assert settings["models"]["primary_asr_backend"] == "moss"
    assert not [item for item in warnings if "primary_asr_backend" in item]

    settings, warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {"models": {"primary_asr_backend": "sensevoice"}},
    )
    assert settings["models"]["primary_asr_backend"] == "sensevoice"
    assert not warnings


def test_cuda_requirements_follow_selected_combination():
    cpu_settings = {
        "models": {
            "primary_asr_backend": "sensevoice",
            "firered_asr_backend": "off",
            "qwen_asr_backend": "off",
        }
    }
    assert selected_cuda_components(cpu_settings) == []
    assert not combination_requires_cuda(cpu_settings)

    api_settings = {
        "models": {
            "primary_asr_backend": "api",
            "firered_asr_backend": "off",
            "qwen_asr_backend": "off",
        }
    }
    assert not combination_requires_cuda(api_settings)

    cuda_settings = {
        "models": {
            "primary_asr_backend": "whisper_turbo",
            "firered_asr_backend": "qwen_aligner",
            "qwen_asr_backend": "local",
        }
    }
    # Qwen3-ForcedAligner runs on CPU without CUDA since 2026-10-13.
    assert selected_cuda_components(cuda_settings) == [
        "Qwen3-ASR 本地文字复核",
    ]


def test_invalid_primary_backend_falls_back_to_moss():
    settings, warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {"models": {"primary_asr_backend": "not-real"}},
    )
    assert settings["models"]["primary_asr_backend"] == "moss"
    assert any("primary_asr_backend" in item for item in warnings)


def test_whisper_is_a_valid_optional_subtitle_timeline():
    settings, warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {"models": {"firered_asr_backend": "whisper_turbo"}},
    )
    assert settings["models"]["firered_asr_backend"] == "whisper_turbo"
    assert not [item for item in warnings if "firered_asr_backend" in item]


def test_lightweight_vad_needs_no_firered_model():
    import moss_firered_pipeline as pipeline

    class Legacy:
        AUDIO_SAMPLE_RATE = 16000

    audio = np.zeros(16000 * 2, dtype=np.float32)
    audio[4000:12000] = 0.15 * np.sin(np.linspace(0, 160 * np.pi, 8000))
    regions = pipeline.detect_lightweight_vad(audio, Legacy())
    assert regions
    assert regions[0]["start"] < regions[0]["end"]


def test_dynamic_primary_and_lightweight_vad_cache_stages_are_registered(tmp_path):
    from twobyteasr.cache import cache_stage_signature, run_cached_stage

    lightweight = cache_stage_signature(
        "lightweight_vad", {"engine": "energy-v1", "sample_rate": 16000}
    )
    sensevoice = cache_stage_signature(
        "primary_sensevoice", {"backend": "sensevoice", "vad": []}
    )
    paraformer = cache_stage_signature(
        "primary_paraformer", {"backend": "paraformer", "vad": []}
    )
    assert lightweight
    assert sensevoice
    assert paraformer
    assert sensevoice != paraformer

    context = {"cache_dir": str(tmp_path), "identity": "test-media"}
    first = run_cached_stage(
        "primary_sensevoice",
        context,
        lambda: [{"start": 0.0, "end": 1.0, "text": "测试"}],
        extra_signature={"backend": "sensevoice", "vad": []},
    )
    second = run_cached_stage(
        "primary_sensevoice",
        context,
        lambda: (_ for _ in ()).throw(AssertionError("cache was not reused")),
        extra_signature={"backend": "sensevoice", "vad": []},
    )
    assert second == first
