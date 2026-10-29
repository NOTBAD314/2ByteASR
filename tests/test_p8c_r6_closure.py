from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.providers.llm_config import (
    activate_ai_service,
    active_service_values,
    resolved_service_values,
    service_model_catalog,
)
from twobyteasr.subtitle_rules.studio_review import (
    audit_current_project_review,
    review_hypotheses_from_project,
    ReviewEvidenceAggregator,
)
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, StudioCue
from twobyteasr.studio.studio_ui import MpvCanvas, SubtitleStudioPage


def _app():
    return QApplication.instance() or QApplication([])


def test_shared_provider_catalog_heals_cross_provider_model():
    settings = {
        "models": {
            "ai_service": "deepseek",
            "provider_profiles": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "gemini-3.7-flash-high",
                    "protocol": "auto",
                },
            },
        },
    }
    values = resolved_service_values(settings, "deepseek")
    assert values["model"] == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in service_model_catalog(settings, "deepseek")
    assert not any(item.startswith("gemini-") for item in service_model_catalog(settings, "deepseek"))
    activate_ai_service(settings, "antigravity")
    assert active_service_values(settings)["model"] == ""  # CLI default is not guessed
    settings["models"]["provider_profiles"]["antigravity"]={"model":"gemini-3.7-flash-high"}
    assert active_service_values(settings)["model"] == "gemini-3.7-flash-high"


def test_audio_external_clock_is_adopted_by_project_clock():
    _app()
    sample = {
        "state": "SYNCED",
        "source_path": "audio.mp3",
        "estimated_source_ms": 1200,
        "clock_sequence": 1,
        "source_generation": 1,
        "clock_monotonic_ts": 1.0,
        "paused": False,
        "effective_rate": 1.0,
    }
    canvas = MpvCanvas()
    canvas._duration = 10.0
    canvas.set_external_clock_provider(lambda: sample, enabled=True)
    assert canvas._observe_external_clock() is True
    assert canvas.playback_position_snapshot().presentation_media_ms == 1200
    canvas.deleteLater()


def test_audio_endpoint_completes_its_startup_without_waiting_for_mpv_frame():
    _app()
    sample=dict(state='SYNCED',source_path='audio.wav',estimated_source_ms=1000,clock_sequence=1,
        source_generation=1,clock_monotonic_ts=1.,paused=True,effective_rate=1.,decoded_bytes=4096)
    canvas=MpvCanvas();canvas._duration=10.;canvas._startup_state='MEDIA_OPENING';canvas._media_has_video=False
    canvas.set_external_clock_provider(lambda:sample,enabled=True)
    assert canvas._observe_external_clock() and canvas._startup_state=='READY'
    canvas.deleteLater()


def test_review_audit_action_requires_current_project(tmp_path, monkeypatch):
    project = SubtitleProject(
        media=StudioMedia(path="", duration_ms=1000),
        cues=[StudioCue("cue-1", 0, 1000, "示例")],
    )
    monkeypatch.setattr(
        "twobyteasr.subtitle_rules.studio_review.studio_data_root",
        lambda: tmp_path / "SubtitleStudioPreview",
    )
    output = audit_current_project_review(project, project_path=tmp_path / "current.2byteproj")
    assert output["total"] == 1
    assert set(output["final_buckets"]) == {"AUTO_ACCEPT", "SUGGEST_CONFIRM", "NEEDS_REVIEW"}
    assert "top_reasons" in output


def test_review_audit_does_not_turn_missing_model_support_into_project_wide_risk(
    tmp_path, monkeypatch,
):
    project = SubtitleProject(
        media=StudioMedia(path="audio.mp3", duration_ms=3_000),
        cues=[
            StudioCue("cue-1", 0, 1_000, "第一句", evidence_refs=["segment:1"]),
            StudioCue("cue-2", 1_100, 2_100, "第二句", evidence_refs=["segment:2"]),
        ],
        asr_evidence={
            "segment:1": {
                "start_ms": 0,
                "end_ms": 1_000,
                "text": "第一句",
                "moss_text": "第一句",
                "primary_source": "moss-host",
                "confidence": 0.5,
            },
            "segment:2": {
                "start_ms": 1_100,
                "end_ms": 2_100,
                "text": "第二句",
                "moss_text": "第二句",
                "primary_source": "moss-host",
                "confidence": 0.5,
            },
        },
    )
    assert [row["text"] for row in review_hypotheses_from_project(project, project.cues[0])] == [
        "第一句"
    ]
    monkeypatch.setattr(
        "twobyteasr.subtitle_rules.studio_review.studio_data_root",
        lambda: tmp_path / "SubtitleStudioPreview",
    )
    output = audit_current_project_review(project, project_path=tmp_path / "current.2byteproj")
    assert output["final_buckets"] == {
        "AUTO_ACCEPT": 2,
        "SUGGEST_CONFIRM": 0,
        "NEEDS_REVIEW": 0,
    }
    assert output["distribution"] == {
        "LEXICAL": 0,
        "BOUNDARY": 0,
        "SPEAKER": 0,
        "TIMING": 0,
    }
    assert output["risk_category_counts"] == {
        "LEXICAL": 0,
        "BOUNDARY": 0,
        "SPEAKER": 0,
        "TIMING": 0,
        "MIXED": 0,
    }
    assert output["top_reasons"] == []


def test_review_treats_cross_cue_asr_segment_as_boundary_evidence():
    cue = StudioCue("cue-1", 1_000, 2_000, "当前这一句", evidence_refs=["segment:1"])
    project = SubtitleProject(
        media=StudioMedia(path="audio.mp3", duration_ms=4_000),
        cues=[cue],
        asr_evidence={
            "segment:1": {
                "start_ms": 500,
                "end_ms": 2_500,
                "text": "前一句当前这一句后一句",
                "moss_text": "前一句当前这一句后一句",
                "primary_source": "moss-host",
            }
        },
    )
    aggregate = ReviewEvidenceAggregator().aggregate(
        cue, review_hypotheses_from_project(project, cue)
    )
    assert aggregate.models_agree_text is True
    # A neighboring transcript is context; without words its exact coverage
    # is unknown and cannot be certified as complete cue-local evidence.
    assert aggregate.requires_review is True
    assert aggregate.source_coverage['coverage_unknown']
    assert aggregate.risk_types == ()


def test_qc_does_not_relabel_cross_cue_moss_text_as_model_conflict():
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine

    cue = StudioCue("cue-1", 1_000, 2_000, "当前这一句", evidence_refs=["segment:1"])
    project = SubtitleProject(
        media=StudioMedia(path="audio.mp3", duration_ms=4_000),
        cues=[cue],
        asr_evidence={
            "segment:1": {
                "start_ms": 500,
                "end_ms": 2_500,
                "text": "前一句当前这一句后一句",
                "moss_text": "前一句当前这一句后一句",
                "primary_source": "moss-host",
            }
        },
    )
    issues = SubtitleQCEngine().analyze(project).for_cue(cue.id)
    assert "model_disagreement" not in {item.issue_type for item in issues}


def test_identical_pixels_do_not_suppress_next_cue_activation(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path="audio.mp3", duration_ms=5_000),
        cues=[
            StudioCue("cue-1", 0, 1_000, "相同字幕"),
            StudioCue("cue-2", 2_000, 3_000, "相同字幕"),
        ],
    )
    page = SubtitleStudioPage()
    page.project = project
    active = [project.cues[0]]
    published = []
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    monkeypatch.setattr(page,"_prepared_caption_snapshot",lambda cue_id,width,height:build_visual_cue_snapshot(project,cue_id,width=width,height=height,fps=30))
    monkeypatch.setattr(page, "_renderer_cue_at_playhead", lambda: active[0])
    monkeypatch.setattr(
        page,
        "_publish_advanced_live",
        lambda snapshot, identity: published.append((snapshot, identity)),
    )
    try:
        page.timeline.playhead_ms = project.cues[0].start_ms
        page._schedule_advanced_preview({}, queue_fidelity=False)
        first = page._advanced_preview_state.identity
        assert first is not None

        active[0] = project.cues[1]
        page.timeline.playhead_ms = project.cues[1].start_ms
        page._schedule_advanced_preview({}, queue_fidelity=False)
        second = page._advanced_preview_state.identity

        assert second is not None
        assert first.request_key == second.request_key
        assert first.snapshot_hash != second.snapshot_hash
        assert second.cue_id == "cue-2"
        assert [identity.cue_id for _snapshot, identity in published] == ["cue-1", "cue-2"]
    finally:
        page.close_page()
        page.deleteLater()
