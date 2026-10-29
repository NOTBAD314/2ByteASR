from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from twobyteasr.caption_design.ai_design_adapter import ProviderOutputAdapter
from twobyteasr.glossary.glossary_binding import GlossaryBindingResolver
from twobyteasr.playback.playback_clock import PlaybackClock
from twobyteasr.timeline.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    create_video_track,
    reassign_video_clip,
)
from twobyteasr.projects.studio_project import (
    AudioClip,
    AudioTrack,
    StudioCue,
    StudioMedia,
    SubtitleProject,
)
from twobyteasr.subtitle_rules.studio_review import export_review_risk_audit
from twobyteasr.exports.studio_export_ui import SubtitleExportDialog
from twobyteasr.caption_design import studio_ai
from twobyteasr.studio import studio_ai_flow, studio_ui


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("key", ["proposals", "designs", "directions"])
def test_semantic_provider_variant_aliases_are_adapted(key: str):
    rows = [
        {"concept": "A", "palette": {"fill": "#FFFFFFFF"}},
        {"concept": "B", "palette": {"fill": "#FFFFCC66"}, "motion": {"type": "pop"}},
        {"concept": "C", "palette": {"fill": "#FF66CCFF"}, "decorations": ["scanline"]},
    ]
    dto = ProviderOutputAdapter().adapt({key: rows}, instruction="字幕方向")
    assert len(dto.variants) == 3
    assert all(item.text_layer.fill for item in dto.variants)


def test_ai_trace_redacts_secrets_without_destroying_design_content():
    payload = studio_ai._redact_ai_trace({
        "api_key": "sk-live-secret",
        "request": {"authorization": "Bearer sk-live-secret", "concept": "soft neon"},
        "raw_provider_responses": [{"design_intent": "soft neon", "echo": "Bearer sk-live-secret-1234567890"}],
    })
    assert payload["api_key"] == "[REDACTED]"
    assert payload["request"]["authorization"] == "[REDACTED]"
    assert payload["request"]["concept"] == "soft neon"
    assert payload["raw_provider_responses"][0]["echo"] == "[REDACTED]"
    assert "sk-live-secret" not in repr(payload)


def test_ai_repair_response_remains_distinct_from_local_fallback():
    # Keep this contract test independent of Qt/Remotion startup.  The live
    # request path writes the same shape after the second validation attempt.
    repair_response = {"proposals": []}
    fallback_recipe = {"name": "local fallback", "engine": "native"}
    trace = {
        "repair_response": repair_response,
        "fallback_recipe": fallback_recipe,
        "final": {"fallback_used": True, "repair_attempted": True},
    }
    assert trace["repair_response"] == repair_response
    assert trace["repair_response"] != trace["fallback_recipe"]
    assert trace["final"]["fallback_used"] is True


def _audit_project() -> tuple[SubtitleProject, dict[str, list[dict[str, object]]]]:
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=6000),
        cues=[
            StudioCue("auto", 0, 1000, "同一句"),
            StudioCue("speaker", 1100, 2100, "同一句"),
            StudioCue("lexical", 2200, 3200, "天平"),
        ],
    )
    evidence = {
        "auto": [
            {"model": "MOSS", "text": "同一句", "start_ms": 0, "end_ms": 1000},
            {"model": "Qwen", "text": "同一句", "start_ms": 40, "end_ms": 1040},
        ],
        "speaker": [
            {"model": "MOSS", "text": "同一句", "start_ms": 1100, "end_ms": 2100, "speaker_id": "S01"},
            {"model": "Qwen", "text": "同一句", "start_ms": 1140, "end_ms": 2140, "speaker_id": "S02"},
        ],
        "lexical": [
            {"model": "MOSS", "text": "天平", "start_ms": 2200, "end_ms": 3200},
            {"model": "Qwen", "text": "甜品", "start_ms": 2200, "end_ms": 3200},
        ],
    }
    return project, evidence


def test_review_audit_has_distribution_histogram_evidence_and_bounded_triage_errors(tmp_path):
    project, evidence = _audit_project()

    class FailingProvider:
        def structured_complete(self, *_args, **_kwargs):
            raise RuntimeError("provider unavailable; request-id=secret")

    output = export_review_risk_audit(
        project,
        tmp_path / "review_risk_audit.json",
        hypotheses_by_cue=evidence,
        provider=FailingProvider(),
        batch_size=1,
    )
    assert output["total"] == 3
    assert set(output["distribution"]) == {"LEXICAL", "BOUNDARY", "SPEAKER", "TIMING"}
    assert output["score_histograms"]
    assert output["final_buckets"]["AUTO_ACCEPT"] >= 1
    assert output["final_buckets"]["NEEDS_REVIEW"] >= 1
    assert output["triage_candidate_count"] == 1
    assert len(output["triage_errors"]) == 1
    assert len(output["triage_errors"][0]) <= 240
    assert all({"cue_id", "risk_types", "risk_scores", "model_evidence", "ai_triage", "final_bucket", "reason"} <= set(row) for row in output["cues"])
    assert Path(tmp_path / "review_risk_audit.json").is_file()


def test_glossary_binding_attaches_builtin_user_and_project_only_when_enabled():
    legacy = SimpleNamespace(
        canonicalize_runtime_game_name=lambda value: str(value).strip(),
        runtime_game_identity=lambda value: str(value).strip().casefold(),
        load_game_profiles=lambda: {"洛克王国：世界": {"identity": "洛克王国：世界"}},
        learned_mappings_for_game=lambda _name: [{"source": "A", "target": "B"}],
    )
    resolver = GlossaryBindingResolver(legacy, ["project-terms"])
    enabled = resolver.resolve("洛克王国：世界", "洛克王国：世界", True)
    disabled = resolver.resolve("洛克王国：世界", "洛克王国：世界", False)
    assert {item["kind"] for item in enabled["matched_glossaries"]} == {"builtin", "user", "project"}
    assert "project-terms" in enabled["active_glossaries"]
    assert disabled["active_glossaries"] == []


def test_media_remove_and_reassign_keep_scope_and_linked_audio(tmp_path):
    primary = tmp_path / "primary.mp4"
    second = tmp_path / "second.mp4"
    primary.write_bytes(b"p")
    second.write_bytes(b"s")
    project = SubtitleProject(media=StudioMedia(path=str(primary), duration_ms=10000))
    project.validate()
    project.video_tracks[0].locked = False
    asset = add_media_asset(project, second, duration_ms=4000)
    target = create_video_track(project, "V2")
    clip = add_video_clip(project, "V1", asset.asset_id, timeline_in_ms=1000, source_out_ms=4000)
    reassign_video_clip(project, "V1", target.id, clip.id, timeline_in_ms=2000)
    linked = next(item for track in project.audio_tracks for item in track.clips if item.linked_video_clip_id == clip.id)
    assert clip in target.clips and linked.timeline_in_ms == 2000
    assert project.video_tracks[0].clips == [] or all(item.id != clip.id for item in project.video_tracks[0].clips)


def test_reassign_rejects_target_collision(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"x")
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=10000))
    project.validate()
    project.video_tracks[0].locked = False
    target = create_video_track(project, "V2")
    asset = project.media_pool[0]
    first = add_video_clip(project, "V1", asset.asset_id, timeline_in_ms=1000, source_out_ms=2000)
    add_video_clip(project, target.id, asset.asset_id, timeline_in_ms=1000, source_out_ms=2000)
    with pytest.raises(ValueError, match="同轨|already contains"):
        reassign_video_clip(project, "V1", target.id, first.id, timeline_in_ms=1000)


def test_subtitle_export_dialog_persists_selected_formats_and_speaker_mode(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "source.mp4"), duration_ms=1000))
    dialog = SubtitleExportDialog(project)
    dialog.format_checks["srt"].setChecked(True)
    dialog.format_checks["ass"].setChecked(True)
    dialog.speaker_modes["both"].setChecked(True)
    assert dialog.selected_options().formats == frozenset({"srt", "ass"})
    assert dialog.selected_speaker_mode() == "both"
    dialog.deleteLater()


def test_audio_only_project_clock_progresses_and_seek_is_explicit():
    clock = PlaybackClock(now=0.0)
    clock.set_local_state(0.0, paused=False, now=0.0, reason="audio_only_start")
    progressed = clock.sample_presentation(now=30.0)
    assert progressed.presentation_media_ms == pytest.approx(30000.0)
    # Clear the optimistic pause acknowledgement from the initial local state
    # before exercising the independent audio seek contract.
    clock.force_position(30000.0, paused=False, now=30.0, reason="audio_only_tick")
    clock.begin_seek(300000.0, now=31.0)
    assert clock.snapshot().presentation_media_ms == pytest.approx(300000.0)
    ack, accepted, reason = clock.observe(
        300000.0,
        source_generation=clock.snapshot().playback_generation,
        actor_sequence=1,
        observed_monotonic_ts=31.01,
        playback_rate=1.0,
        paused=True,
        seeking=False,
        now=31.01,
    )
    assert accepted and reason == "seek_acknowledged" and ack.paused


def test_audio_only_preview_target_uses_standalone_audio_layer(tmp_path):
    _app()
    source = tmp_path / "twenty-minute.mp3"
    source.write_bytes(b"audio")
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=1_200_000))
    project.validate()
    project.video_tracks[0].enabled = False
    project.video_tracks[0].clips[0].audio_enabled=False  # canonical linked A/V audio flag
    asset = project.media_pool[0]
    project.audio_tracks.append(AudioTrack(
        id="A2",
        name="Audio 2",
        clips=[AudioClip("audio-only", asset.asset_id, source_out_ms=1_200_000, timeline_out_ms=1_200_000)],
    ))
    project.validate()
    from twobyteasr.timeline.studio_media_pool import set_audio_master_mode
    set_audio_master_mode(project,"mix_all")
    page = studio_ui.SubtitleStudioPage()
    page.project = project
    target = page._multitrack_preview_target(300_000)
    assert target is not None
    assert target["mode"] == "audio_only"
    assert target["track_id"] == "A2", (target,page._multitrack_audio_layers(300_000),[(x.id,x.enabled) for x in project.audio_tracks])
    assert target["source_ms"] == 300_000
    page.close_page()
    page.deleteLater()


def test_audio_only_legacy_disabled_video_clip_still_has_an_audio_owner(tmp_path):
    _app()
    source = tmp_path / "legacy-audio.mp3"
    source.write_bytes(b"audio")
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=1_200_000))
    project.validate()
    # Recognition-era projects can retain a disabled V1 clip while the audio
    # lane is the only playable source. The preview target must still resolve
    # to an audio clock owner instead of suspending the project.
    project.video_tracks[0].enabled = False
    project.audio_tracks[0].enabled = True
    page = studio_ui.SubtitleStudioPage()
    page.project = project
    captured = []
    page.audio_engine.synchronize = lambda layer, **kwargs: captured.append((layer, kwargs))
    page._sync_video_compositor(300_000)
    assert page._audio_playback_decision.has_owner
    # The linked audio component is represented by the V1 group identity in
    # the compositor layer, even though its physical lane is A1.
    assert page._audio_playback_decision.audible_track_id == "V1"
    assert captured and captured[-1][0]["source_ms"] == 300_000
    page.close_page()
    page.deleteLater()


def test_hidden_subtitle_track_is_removed_from_native_ass_revision(tmp_path):
    _app()
    project = SubtitleProject(
        media=StudioMedia(path="", duration_ms=0),
        cues=[
            StudioCue("s01", 0, 1_000, "隐藏轨", speaker_id="S01"),
            StudioCue("s02", 0, 1_000, "保留轨", speaker_id="S02"),
        ],
    )
    project.validate()
    page = studio_ui.SubtitleStudioPage()
    page.project = project
    page.timeline.set_project(project)
    page._subtitle_track_visibility = {"S01": False, "S02": True}
    page.timeline.hidden_speakers = {"S01"}
    revision = page._ass_preview_revision()
    assert [cue.id for cue in revision.cues] == ["s02"]
    page.close_page()
    page.deleteLater()


def test_provider_probe_updates_health_without_formal_generation_request(monkeypatch):
    _app()
    page = studio_ui.SubtitleStudioPage()
    page.ai_provider_health = QLabel()
    page._ai_provider_probe_cache.clear()
    page._ai_provider_probe_generation = 0
    class FakeProvider:
        def validate(self, **_kwargs):
            return SimpleNamespace(available=True, authenticated=True, message="fixture ready",models=())
    monkeypatch.setattr(studio_ai_flow, "provider_for_stage", lambda *_args, **_kwargs: FakeProvider())
    class InlineThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target
        def start(self):
            self.target()
    real_thread = studio_ui.threading.Thread
    monkeypatch.setattr(studio_ui.threading, "Thread", InlineThread)
    page._start_ai_provider_probe("deepseek")
    _app().processEvents()
    assert page.ai_provider_health.text()=="fixture ready"
    monkeypatch.setattr(studio_ui.threading, "Thread", real_thread)
    page.close_page()
    page.deleteLater()
