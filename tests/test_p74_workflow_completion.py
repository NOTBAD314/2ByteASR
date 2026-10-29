import json

from twobyteasr.caption_style.font_system import SystemFontEntry, resolve_source_han_heavy
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
)
from twobyteasr.subtitle_rules.studio_review import (
    ReviewReasonCode,
    ReviewSeverity,
    analyze_review_risks,
)
from twobyteasr.exports.studio_subtitle_export import (
    SubtitleExportOptions,
    export_subtitle_artifacts,
    verify_subtitle_artifact,
)
from twobyteasr.caption_style.style_presets import BUILTIN_PRESETS, StylePresetStore


def _calibration_project():
    return SubtitleProject(
        media=StudioMedia(path="D:/calibration.mp4", duration_ms=12_000),
        cues=[
            StudioCue("wrong", 0, 900, "布鲁斯斯", evidence_refs=["wrong-evidence"]),
            StudioCue("correct", 2_000, 4_000, "空中打拳", evidence_refs=["correct-evidence"]),
            StudioCue("ambiguous", 5_000, 6_200, "星见鸦", evidence_refs=["ambiguous-evidence"]),
        ],
        asr_evidence={
            "wrong-evidence": {
                "start_ms": 0,
                "end_ms": 900,
                "moss_text": "布鲁斯",
                "qwen_asr_text": "布鲁斯斯",
                "firered_text": "布鲁斯",
                "confidence": 0.44,
            },
            "correct-evidence": {
                "start_ms": 2_000,
                "end_ms": 4_000,
                "moss_text": "空中打拳",
                "qwen_asr_text": "空中打拳",
                "firered_text": "空中打拳",
                "confidence": 0.98,
            },
            "ambiguous-evidence": {
                "start_ms": 5_000,
                "end_ms": 6_200,
                "moss_text": "星见鸦",
                "qwen_asr_text": "星见雅",
                "confidence": 0.68,
            },
        },
    )


def test_review_calibration_has_true_positive_true_negative_and_ambiguous_case():
    risks = analyze_review_risks(_calibration_project())

    assert risks["wrong"].severity in {
        ReviewSeverity.MUST_REVIEW,
        ReviewSeverity.SUGGEST_REVIEW,
    }
    assert any(item.reason_code is ReviewReasonCode.MODEL_DISAGREEMENT for item in risks["wrong"].items)
    assert risks["correct"].level == "confident"
    assert risks["correct"].severity is ReviewSeverity.INFO
    assert risks["ambiguous"].severity in {
        ReviewSeverity.MUST_REVIEW,
        ReviewSeverity.SUGGEST_REVIEW,
    }
    codes = [item.reason_code for item in risks["wrong"].items]
    assert len(codes) == len(set(codes))


def _speaker_project():
    return SubtitleProject(
        media=StudioMedia(path="D:/video.mp4", duration_ms=5_000, width=1920, height=1080),
        speakers=[
            StudioSpeaker("host", "主播"),
            StudioSpeaker("bruce", "布鲁斯"),
        ],
        cues=[
            StudioCue("a", 100, 1_000, "你好，世界", speaker_id="host"),
            StudioCue("b", 1_500, 2_900, "空中打拳", speaker_id="bruce"),
        ],
    )


def test_subtitle_export_can_emit_only_srt_combined_and_per_speaker(tmp_path):
    project = _speaker_project()
    artifacts = export_subtitle_artifacts(
        project,
        tmp_path,
        "测试视频",
        SubtitleExportOptions(frozenset({"srt"}), "both"),
    )

    assert {item.path.name for item in artifacts} == {
        "测试视频.srt",
        "测试视频_host.srt",
        "测试视频_bruce.srt",
    }
    assert {item.format for item in artifacts} == {"srt"}
    for artifact in artifacts:
        scoped = project if not artifact.speaker_id else SubtitleProject(
            media=project.media,
            speakers=project.speakers,
            cues=[cue for cue in project.cues if cue.speaker_id == artifact.speaker_id],
        )
        verification = verify_subtitle_artifact(artifact, scoped)
        assert verification.valid
        assert verification.cue_count == artifact.cue_count


def test_all_subtitle_formats_roundtrip_unicode_timing_and_speaker_mapping(tmp_path):
    project = _speaker_project()
    artifacts = export_subtitle_artifacts(
        project,
        tmp_path,
        "all-formats",
        SubtitleExportOptions(frozenset({"srt", "ass", "txt", "json"}), "combined"),
    )
    assert {item.format for item in artifacts} == {"srt", "ass", "txt", "json"}
    ass = next(item for item in artifacts if item.format == "ass").path.read_text(encoding="utf-8")
    assert ",host," in ass and ",bruce," in ass
    payload = json.loads(next(item for item in artifacts if item.format == "json").path.read_text(encoding="utf-8"))
    assert [row["text"] for row in payload["cues"]] == ["你好，世界", "空中打拳"]


def test_builtin_preset_delete_is_tombstone_and_restore(tmp_path):
    store = StylePresetStore(tmp_path)
    assert "game" in store.all()
    store.delete("game")
    assert "game" not in store.all()
    assert store.hidden_builtin_ids() == frozenset({"game"})

    store.save_user([])
    assert "game" not in store.all()
    assert store.restore_builtins() == 1
    assert "game" in store.all()
    assert set(BUILTIN_PRESETS).issubset(store.all())


def test_builtin_preset_favorite_and_export_are_real_library_operations(tmp_path):
    store = StylePresetStore(tmp_path)
    store.set_favorite("game", True)

    assert store.favorite_builtin_ids() == frozenset({"game"})
    assert store.load_metadata()["game"]["favorite"] is True
    store.save_user([])
    assert store.favorite_builtin_ids() == frozenset({"game"})

    exported = tmp_path / "game-style.json"
    assert store.export_file(exported, ["game"]) == 1
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["presets"][0]["id"] == "game"
    assert payload["presets"][0]["source"] == "builtin"


def test_source_han_heavy_alias_resolution_prefers_real_heavy_face():
    face = resolve_source_han_heavy((
        SystemFontEntry("Microsoft YaHei UI", ("Regular", "Bold")),
        SystemFontEntry("Source Han Sans SC", ("Regular", "Heavy")),
    ))
    assert face.family == "Source Han Sans SC"
    assert face.style == "Heavy"
    assert face.weight == 800
    assert face.source_han
