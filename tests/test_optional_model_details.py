"""Semantic tests for optional Workshop metadata, with no Qt/model imports."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "optional_model_details_under_test", ROOT / "twobyteasr/recognition/optional_model_details.py"
)
details = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(details)


@pytest.fixture
def manifest(monkeypatch):
    value = json.loads((ROOT / "licenses/optional-models/manifest.json").read_text("utf-8"))
    monkeypatch.setattr(details, "_metadata", lambda: value)
    return value


@pytest.mark.parametrize("key,variant", [
    ("vibevoice", None), ("vibevoice", "vibevoice_1_5b"),
    ("vibevoice", "vibevoice_7b"), ("vibevoice_7b", None), ("diarizen", None),
])
def test_profiles_supply_real_dialog_fields_and_nonempty_extra_sections(manifest, key, variant):
    profile = details.optional_model_technical_info(key, variant)
    official = profile["official"]
    for field in ("developer", "params", "languages", "language_summary", "architecture",
                  "dialects", "audio_type", "license", "runtime", "code_switching",
                  "singing_support", "language_source"):
        assert official[field]
        assert official[field] != "—"
    assert profile["model_type"]
    assert profile["responsibility"] and profile["capabilities"]
    assert all(section["heading"] and section["body"].strip() for section in profile["sections"])
    assert len({section["heading"] for section in profile["sections"]}) == len(profile["sections"])
    for field in ("principles", "strengths", "limits", "resources", "license_notice"):
        assert profile[field].strip()


def test_family_downloads_and_verifications_remain_separate(manifest):
    family = details.optional_model_technical_info("vibevoice")
    versions = family["variants"]
    assert set(versions) == {"vibevoice_1_5b", "vibevoice_7b"}
    for key, version in versions.items():
        spec = manifest["components"][key]
        assert version["download_bytes"] == spec["expected_bytes"]
        assert version["download_files"] == tuple(spec["required_files"])
        assert version["revision"] == spec["revision"]
        assert version["path"] == spec["path"]
    small = versions["vibevoice_1_5b"]["project_validation"]
    large = versions["vibevoice_7b"]["project_validation"]
    assert small["status"] == "degraded_success" and small["inference_validated"] is True
    assert large["status"] == "blocked" and large["inference_validated"] is False
    assert small["quality_validated"] is large["quality_validated"] is False
    assert "人工真值" in small["summary"] and "加载 0 次、推理 0 次" in large["summary"]
    assert versions["vibevoice_1_5b"]["conditions"] != versions["vibevoice_7b"]["conditions"]
    assert small["tested_gpu_total_bytes"] == large["gpu_total_bytes"] == 17066033152
    assert large["bf16_parameter_minimum_bytes"] == 17348043714
    assert large["bf16_parameter_minimum_bytes"] > large["gpu_total_bytes"]
    assert "degraded_success" in versions["vibevoice_1_5b"]["conditions_short"]
    assert "声学质量未验证" in versions["vibevoice_1_5b"]["conditions_short"]
    assert "16.16 GiB" in versions["vibevoice_7b"]["conditions_short"]
    assert "15.89 GiB" in versions["vibevoice_7b"]["conditions_short"]
    assert "推理未执行" in versions["vibevoice_7b"]["conditions_short"]


@pytest.mark.parametrize("key", ["vibevoice_1_5b", "vibevoice_7b"])
def test_explicit_version_has_only_its_own_payload_and_model_card(manifest, key):
    profile = details.optional_model_technical_info("vibevoice", key)
    assert set(profile["variants"]) == {key}
    version = profile["variants"][key]
    assert profile["official"]["params"] == version["parameters"]
    other = "vibevoice_7b" if key == "vibevoice_1_5b" else "vibevoice_1_5b"
    assert all(manifest["components"][other]["repository"] not in item["url"] for item in profile["sources"])


def test_streaming_language_list_is_official_ten_not_nonstreaming_fifty(manifest):
    official = details.optional_model_technical_info("vibevoice")["official"]
    assert set(official["languages"]) == {"中文", "英语", "法语", "德语", "意大利语", "日语", "韩语", "葡萄牙语", "俄语", "西班牙语"}
    assert official["languages_fully_enumerated"] is True
    assert "50" not in official["language_summary"]
    diari = details.optional_model_technical_info("diarizen")["official"]
    assert diari["languages_fully_enumerated"] is False
    assert "不输出 ASR 文字" in diari["languages"][0]


def test_download_bytes_follow_manifest_not_display_estimates(manifest):
    manifest["components"]["vibevoice_7b"]["expected_bytes"] = 123456789
    version = details.optional_model_technical_info("vibevoice", "vibevoice_7b")["variants"]["vibevoice_7b"]
    assert version["download_bytes"] == 123456789
    diari = details.optional_model_technical_info("diarizen")
    assert diari["download_components"] == {"diarizen": 278345340, "diarizen_embedding": 26648958}
    assert diari["download_bytes"] == 304994298


def test_diarizen_parameter_scope_and_layered_licenses_are_explicit(manifest):
    profile = details.optional_model_technical_info("diarizen")
    assert profile["model_type"] == "说话人分析"
    assert profile["official"]["params"] == "63.3M（剪枝 WavLM 主干）"
    assert "不含整个流水线" in profile["principles"]
    notice = profile["license_notice"]
    for required in ("MIT", "CC-BY-NC-4.0", "非商用", "研究/学术", "SA/NC", "CC-BY-4.0", "PLDA", "embedding", "不授予额外商业权利"):
        assert required in notice
    paths = {item["path"] for item in profile["license_documents"]}
    assert "licenses/optional-models/diarizen/MODEL_LICENSE" in paths
    assert "licenses/optional-models/diarizen/UPSTREAM_README.md" in paths
    assert "licenses/optional-models/diarizen/plda/LICENSE" in paths
    assert profile["project_validation"]["quality_validated"] is False


def test_sources_pin_official_revisions_and_new_manifest_identity_is_unvalidated(manifest):
    profile = details.optional_model_technical_info("diarizen")
    for source in profile["sources"]:
        assert source["url"].startswith(("https://huggingface.co/", "https://github.com/"))
        assert "/main/" not in source["url"]
    manifest["components"]["vibevoice_1_5b"]["revision"] = "new-unverified-revision"
    version = details.optional_model_technical_info("vibevoice_1_5b")["variants"]["vibevoice_1_5b"]
    assert version["project_validation"]["status"] == "unvalidated"
    assert version["project_validation"]["inference_validated"] is False
    assert "new-unverified-revision" == version["revision"]
    assert "R3 资源与推理证据不适用" in version["conditions_short"]
    assert "tested_gpu_total_bytes" not in version["project_validation"]


@pytest.mark.parametrize("key,variant", [
    ("vibevoice", "missing"), ("vibevoice_1_5b", "vibevoice_7b"), ("diarizen", "vibevoice_1_5b"),
])
def test_invalid_version_never_silently_falls_back(manifest, key, variant):
    with pytest.raises(ValueError):
        details.optional_model_technical_info(key, variant)


def test_unknown_key_needs_no_manifest_or_runtime(monkeypatch):
    def unexpected():
        raise AssertionError("non-optional profile read installation metadata")
    monkeypatch.setattr(details, "_metadata", unexpected)
    assert details.optional_model_technical_info("moss") == {}


def test_profiles_are_fresh_and_do_not_mutate_registered_metadata(manifest):
    before = copy.deepcopy(manifest)
    first = details.optional_model_technical_info("vibevoice")
    first["official"]["languages"].clear()
    first["variants"]["vibevoice_7b"]["project_validation"]["status"] = "PASS"
    second = details.optional_model_technical_info("vibevoice")
    assert len(second["official"]["languages"]) == 10
    assert second["variants"]["vibevoice_7b"]["project_validation"]["status"] == "blocked"
    assert manifest == before
