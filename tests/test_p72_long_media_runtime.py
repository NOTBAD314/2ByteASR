"""P7.2 long-media, resumable work, and visual residency contracts."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import twobyteasr.playback.waveform_cache as waveform_module
from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
from twobyteasr.rendering.advanced_preview import AdvancedPreviewIdentity
from twobyteasr.recognition.incremental_asr import CueDelta, IncrementalASRPipeline
from twobyteasr.media.media_service import MediaService, ProxyManifest
from twobyteasr.system.resource_governor import ResourceGovernor, ResourceKind
from twobyteasr.storage.runtime_cache import CacheIdentity, RuntimeCacheManager
from twobyteasr.timeline.studio_edit_sequence import (
    EditSequence,
    EditSequenceRuntime,
    HighlightCandidate,
    TemporalIntervalIndex,
    TimelineMarker,
    VideoSegment,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.studio.studio_video_track import _density_pixel_spans, _merged_pixel_spans
from twobyteasr.caption_style.style_recipe import (
    FillSpec, normalize_glow_contract, normalize_shadow_contract,
)
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _gradient_snapshot():
    project = SubtitleProject(
        media=StudioMedia(path="gradient.mp4", duration_ms=5_000, width=1920, height=1080),
        cues=[StudioCue("gradient", 500, 3_500, "BLUE YELLOW", style_id="gradient")],
        styles=[
            SubtitleStyle("default", "Default"),
            SubtitleStyle(
                "gradient", "Gradient", font_family="Arial", font_size=112,
                bold=True, outline_width=0, shadow=0, position_x=960, position_y=540,
            ),
        ],
        style_recipes={
            "gradient": {
                "name": "Blue yellow",
                "engine": "remotion",
                "typography": {},
                "colors": {
                    "fill": FillSpec.linear([
                        {"color": "#FF168BFF", "position": 0.0},
                        {"color": "#FFFFD84A", "position": 1.0},
                    ]).to_dict(),
                },
                "outline": {"width": 0, "shadow": 0},
                "background": {},
                "effects": {},
                "layout": {},
                "motion": {"mode": "none"},
                "ass": {"metadata": "excluded from pixel identity"},
            }
        },
    )
    project.validate()
    return build_visual_cue_snapshot(project, "gradient", width=640, height=360)


def test_static_visual_identity_ignores_runtime_and_non_pixel_metadata():
    snapshot = _gradient_snapshot()
    first = AdvancedPreviewIdentity.from_snapshot(
        snapshot, width=640, height=360, motion_time_ms=10,
    )
    changed_recipe = dict(snapshot.style_recipe)
    changed_recipe.update(name="Renamed", ass={"metadata": "changed"})
    changed = replace(
        snapshot,
        cue_id="different-runtime-id",
        start_ms=123_000,
        end_ms=128_000,
        speaker="other",
        style_recipe=changed_recipe,
        motion_recipe={"mode": "none", "entrance": {"ui_generation": 99}},
    )
    second = AdvancedPreviewIdentity.from_snapshot(
        changed, width=640, height=360, motion_time_ms=2_900,
    )

    assert first.glyph_key == second.glyph_key
    assert first.request_key == second.request_key
    assert first.snapshot_hash != second.snapshot_hash


def test_live_gradient_has_correct_color_variation_within_100ms(app):
    started = time.perf_counter()
    image = render_live_snapshot(_gradient_snapshot(), width=640, height=360)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    opaque = [
        image.pixelColor(x, y)
        for y in range(0, image.height(), 2)
        for x in range(0, image.width(), 2)
        if image.pixelColor(x, y).alpha() >= 192
    ]

    assert not image.isNull()
    assert elapsed_ms < 100.0
    assert opaque
    assert any(color.blue() > color.red() + 20 for color in opaque)
    assert any(color.red() > 180 and color.green() > 140 and color.blue() < 140 for color in opaque)


def _effect_snapshot(*, shadow=0.0, glow=0.0):
    snapshot = _gradient_snapshot()
    shadow_payload = normalize_shadow_contract(shadow)
    glow_payload = normalize_glow_contract({
        "enabled": glow > 0,
        "color": "#FF00FFFF",
        "radius": glow,
        "opacity": 0.72 if glow > 0 else 0.0,
        "intensity": 1.0,
    })
    recipe = json.loads(json.dumps(snapshot.style_recipe))
    recipe.setdefault("outline", {})["shadow"] = shadow_payload
    recipe.setdefault("effects", {})["glow"] = glow_payload
    return replace(
        snapshot,
        shadow=shadow_payload,
        glow=glow_payload,
        style_recipe=recipe,
    )


def _effect_metrics(baseline, candidate):
    extra = 0
    foreground_corrupted = 0
    for y in range(baseline.height()):
        for x in range(baseline.width()):
            before = baseline.pixelColor(x, y)
            after = candidate.pixelColor(x, y)
            if before.alpha() == 0 and after.alpha() > 0:
                extra += 1
            if before.alpha() != 255:
                continue
            before_rgb = before.getRgb()[:3]
            after_rgb = after.getRgb()[:3]
            darkened = sum(before_rgb) - sum(after_rgb) > 24
            hue_shift = max(
                abs(before_rgb[channel] - after_rgb[channel])
                for channel in range(3)
            ) > 16
            if darkened or hue_shift:
                foreground_corrupted += 1
    return extra, foreground_corrupted


@pytest.mark.parametrize("strength", [0.1, 0.5, 1.0])
def test_live_shadow_has_effect_pixels_without_polluting_foreground(app, strength):
    baseline = render_live_snapshot(
        _effect_snapshot(shadow=0.0), width=640, height=360
    )
    candidate = render_live_snapshot(
        _effect_snapshot(shadow=strength), width=640, height=360
    )
    extra, foreground_changed = _effect_metrics(baseline, candidate)
    assert extra > 0
    assert foreground_changed == 0


@pytest.mark.parametrize("radius", [0.1, 0.5, 1.0, 8.0])
def test_live_glow_has_halo_pixels_without_polluting_foreground(app, radius):
    baseline = render_live_snapshot(
        _effect_snapshot(glow=0.0), width=640, height=360
    )
    candidate = render_live_snapshot(
        _effect_snapshot(glow=radius), width=640, height=360
    )
    extra, foreground_changed = _effect_metrics(baseline, candidate)
    assert extra > 0
    assert foreground_changed == 0


def test_live_shadow_and_glow_combine_independently(app):
    shadow = render_live_snapshot(
        _effect_snapshot(shadow=1.0), width=640, height=360
    )
    glow = render_live_snapshot(
        _effect_snapshot(glow=8.0), width=640, height=360
    )
    combined = render_live_snapshot(
        _effect_snapshot(shadow=1.0, glow=8.0), width=640, height=360
    )
    hashes = {
        bytes(image.constBits()) for image in (shadow, glow, combined)
    }
    assert len(hashes) == 3


def test_runtime_cache_deduplicates_one_inflight_producer():
    cache = RuntimeCacheManager(memory_budget_bytes=1_024, disk_budget_bytes=1_024)
    release = threading.Event()
    started = threading.Event()
    calls = 0
    results = []

    def producer():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return {"value": 7}

    def caller():
        results.append(cache.get_or_create("shared", producer))

    threads = [threading.Thread(target=caller) for _ in range(6)]
    for thread in threads:
        thread.start()
    assert started.wait(1)
    release.set()
    for thread in threads:
        thread.join(timeout=2)

    assert calls == 1
    assert [produced for _value, produced in results].count(True) == 1
    assert all(value == {"value": 7} for value, _produced in results)
    telemetry = cache.snapshot()["telemetry"]["counts"]
    assert telemetry["generate"] == 1
    assert telemetry["wait_existing"] == 5


def test_runtime_cache_evicts_lru_but_retains_active_and_project_assets(tmp_path):
    cache = RuntimeCacheManager(memory_budget_bytes=8, disk_budget_bytes=8)
    cache.put_memory("active", b"aaaa", size_bytes=4)
    cache.pin("active")
    cache.put_memory("recent", b"bbbb", size_bytes=4)
    cache.put_memory("new", b"cccc", size_bytes=4)
    assert cache.get_memory("active") == b"aaaa"
    assert cache.get_memory("recent") is None
    assert cache.get_memory("new") == b"cccc"

    project_artifact = tmp_path / "project.bin"
    disposable = tmp_path / "disposable.bin"
    project_artifact.write_bytes(b"project")
    disposable.write_bytes(b"dispose")
    cache.register_artifact("project", project_artifact, project_pinned=True)
    cache.register_artifact("disposable", disposable)
    assert project_artifact.is_file()
    assert not disposable.exists()


def test_resource_governor_protects_playback_but_grants_foreground_live():
    governor = ResourceGovernor(background_limit=1)
    governor.set_playback(True)
    background_entered = threading.Event()
    release = threading.Event()

    def background():
        with governor.lease(ResourceKind.WAVEFORM, cancelled=release.is_set) as allowed:
            if allowed:
                background_entered.set()

    thread = threading.Thread(target=background)
    thread.start()
    assert not background_entered.wait(0.08)
    with governor.lease(ResourceKind.ADVANCED_PREVIEW, foreground=True) as allowed:
        assert allowed is True
    governor.set_playback(False)
    assert background_entered.wait(1)
    release.set()
    thread.join(timeout=1)


def test_temporal_indexes_bound_long_project_queries():
    entries = ((index * 1_000, index * 1_000 + 300, index) for index in range(20_000))
    index = TemporalIntervalIndex(entries)
    started = time.perf_counter()
    assert index.query(9_999_900, 10_001_100) == (10_000, 10_001)
    assert (time.perf_counter() - started) * 1000.0 < 10.0

    segments = [
        VideoSegment(f"s{index}", "source.mp4", index * 1_000, index * 1_000 + 800,
                     index * 800, index * 800 + 800)
        for index in range(1_000)
    ]
    candidates = [
        HighlightCandidate(f"c{index}", f"Candidate {index}", index * 1_000, index * 1_000 + 400)
        for index in range(1_000)
    ]
    markers = [TimelineMarker(f"m{index}", index * 800 + 100) for index in range(1_000)]
    sequence = EditSequence(
        source_path="source.mp4", source_duration_ms=1_000_000,
        segments=segments, clip_candidates=candidates, markers=markers,
    )
    runtime = EditSequenceRuntime(sequence)
    assert len(runtime.visible_segments(400_000, 408_000)) <= 11
    assert len(runtime.visible_candidates(400_000, 408_000)) <= 11
    assert len(runtime.visible_markers(400_000, 408_000)) <= 11
    assert runtime.segment_for_source(400_100) is segments[400]
    assert runtime.segment_for_source(999_800) is segments[-1]


def test_dense_timeline_pixel_spans_merge_without_per_pixel_paint_work():
    assert _merged_pixel_spans([(8, 10), (2, 4), (5, 7), (14, 14)]) == (
        (2, 10),
        (14, 14),
    )
    assert _density_pixel_spans([(2, 5), (4, 7), (10, 10)]) == (
        (2, 3, 1),
        (4, 5, 2),
        (6, 7, 1),
        (10, 10, 1),
    )


def test_progressive_waveform_publishes_coarse_then_honors_cancel(tmp_path, monkeypatch):
    media = tmp_path / "media.wav"
    ffmpeg = tmp_path / "ffmpeg.exe"
    media.write_bytes(b"media")
    ffmpeg.write_bytes(b"tool")
    calls = []

    def variant(*_args, key_suffix, **_kwargs):
        calls.append(("variant", key_suffix))
        path = tmp_path / f"cache{key_suffix}"
        path.mkdir(exist_ok=True)
        return path

    monkeypatch.setattr(waveform_module, "_generate_waveform_variant", variant)
    monkeypatch.setattr(
        waveform_module, "generate_waveform_cache",
        lambda *_args, **_kwargs: pytest.fail("full refinement must not run after cancellation"),
    )
    ready = []
    with pytest.raises(InterruptedError, match="refinement cancelled"):
        waveform_module.generate_progressive_waveform_cache(
            media, ffmpeg, cache_root=tmp_path / "root",
            on_ready=lambda tier, path: ready.append((tier, path)),
            before_refine=lambda: False,
        )

    assert calls == [("variant", "-coarse-v1")]
    assert [tier for tier, _path in ready] == ["coarse"]


def test_media_metadata_probe_is_shared_and_invalidates_on_source_change(tmp_path):
    source = tmp_path / "source.mp4"
    ffprobe = tmp_path / "ffprobe.exe"
    source.write_bytes(b"video")
    ffprobe.write_bytes(b"tool")
    calls = []

    def probe(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({
                "format": {"duration": "12.5", "size": str(source.stat().st_size)},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 1920,
                     "height": 1080, "avg_frame_rate": "30000/1001", "time_base": "1/90000",
                     "side_data_list": [{"rotation": -90}]},
                    {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000",
                     "channels": 2, "time_base": "1/48000"},
                ],
            }),
        )

    service = MediaService(
        ffprobe_path=ffprobe, ffmpeg_path=tmp_path / "ffmpeg.exe",
        cache_root=tmp_path / "cache", probe_runner=probe,
        cache_manager=RuntimeCacheManager(memory_budget_bytes=1_000_000),
    )
    first = service.metadata(source)
    second = service.metadata(source)
    source.write_bytes(b"video changed")
    third = service.metadata(source)

    assert first is second
    assert len(calls) == 2
    assert first.duration_ms == 12_500
    assert first.fps == pytest.approx(29.97003, rel=1e-5)
    assert first.rotation == -90
    assert third.source_size != first.source_size
    show_entries = calls[0][calls[0].index("-show_entries") + 1]
    assert "format=duration,size" in show_entries
    assert "avg_frame_rate" in show_entries
    assert "stream_side_data=rotation" in show_entries


def test_proxy_jobs_deduplicate_and_ready_manifest_is_switchable(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    source.write_bytes(b"source")
    ffmpeg.write_bytes(b"tool")
    ffprobe.write_bytes(b"tool")
    service = MediaService(
        ffprobe_path=ffprobe, ffmpeg_path=ffmpeg, cache_root=tmp_path / "cache",
        cache_manager=RuntimeCacheManager(memory_budget_bytes=1_000_000),
    )
    release = threading.Event()
    calls = 0

    def build(path, settings, job):
        nonlocal calls
        calls += 1
        assert release.wait(2)
        proxy = tmp_path / "proxy.mp4"
        proxy.write_bytes(b"proxy")
        identity = service._proxy_identity(path, settings)
        manifest = ProxyManifest(
            identity_key=identity.key, source={}, settings={}, state="READY",
            proxy_path=str(proxy), completed_at=time.time(),
        )
        service._write_manifest(service._proxy_dir(identity) / "manifest.json", manifest)
        return manifest

    monkeypatch.setattr(service, "_build_proxy", build)
    first = service.start_proxy(source)
    second = service.start_proxy(source)
    assert first is second
    release.set()
    manifest = first.wait(2)
    assert calls == 1
    assert manifest is not None and manifest.switch_ready
    assert service.proxy_manifest(source).switch_ready


def test_proxy_service_cancel_and_idle_wait_are_bounded(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    service = MediaService(
        ffprobe_path=tmp_path / "ffprobe.exe",
        ffmpeg_path=tmp_path / "ffmpeg.exe",
        cache_root=tmp_path / "cache",
    )
    started = threading.Event()

    def build(_path, _settings, job):
        started.set()
        while not job.cancelled:
            time.sleep(0.005)
        raise InterruptedError("cancelled")

    monkeypatch.setattr(service, "_build_proxy", build)
    job = service.start_proxy(source)
    assert started.wait(1.0)
    assert service.cancel_all() == 1
    assert service.wait_for_idle(timeout=0.5)
    assert job.done


class _FixtureASR(IncrementalASRPipeline):
    def _extract_chunk(self, spec, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFF" + b"0" * 64)


def test_asr_decodes_next_chunk_while_current_chunk_is_recognized(tmp_path):
    source = tmp_path / "source.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    source.write_bytes(b"source")
    ffmpeg.write_bytes(b"tool")
    next_decode_started = threading.Event()
    calls = []

    class OverlapASR(_FixtureASR):
        def _extract_chunk(self, spec, target):
            super()._extract_chunk(spec, target)
            if spec.index == 1:
                next_decode_started.set()

    def recognize(_path, spec):
        calls.append(spec.index)
        if spec.index == 0:
            assert next_decode_started.wait(1.0)
        return [{"start": 0, "end": 1, "text": f"chunk {spec.index}"}]

    pipeline = OverlapASR(
        source, duration_ms=11_000, backend="fixture", model_revision="r1",
        settings={}, ffmpeg_path=ffmpeg, cache_root=tmp_path / "asr",
        recognize_chunk=recognize, chunk_ms=5_000, overlap_ms=0,
    )

    assert len(pipeline.run()) == 3
    assert calls == [0, 1, 2]


def test_asr_chunks_resume_completed_results_and_invalidate_changed_settings(tmp_path):
    source = tmp_path / "source.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    source.write_bytes(b"source")
    ffmpeg.write_bytes(b"tool")
    calls = []
    events = []

    def recognize(_path, spec):
        calls.append(spec.index)
        return [{"start": 0, "end": 1, "text": f"chunk {spec.index}"}]

    kwargs = dict(
        source_path=source, duration_ms=11_000, backend="fixture",
        model_revision="r1", settings={"language": "zh"}, ffmpeg_path=ffmpeg,
        cache_root=tmp_path / "asr", recognize_chunk=recognize,
        event_sink=events.append, chunk_ms=5_000, overlap_ms=0,
    )
    first = _FixtureASR(**kwargs)
    first_rows = first.run()
    second = _FixtureASR(**kwargs)
    second_rows = second.run()

    assert calls == [0, 1, 2]
    assert first_rows == second_rows
    assert [event.reused for event in events[-3:]] == [True, True, True]
    assert [event.chunk_index for event in events[:3]] == [0, 1, 2]

    changed = _FixtureASR(**{**kwargs, "settings": {"language": "en"}})
    assert changed.identity.key != first.identity.key
    changed.run()
    assert calls == [0, 1, 2, 0, 1, 2]


def test_empty_completed_asr_chunk_is_reused_without_recognition(tmp_path):
    source = tmp_path / "silent.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    source.write_bytes(b"silent")
    ffmpeg.write_bytes(b"tool")
    calls = []

    pipeline = _FixtureASR(
        source, duration_ms=5_000, backend="fixture", model_revision="r1",
        settings={}, ffmpeg_path=ffmpeg, cache_root=tmp_path / "asr",
        recognize_chunk=lambda _path, spec: calls.append(spec.index) or [],
        chunk_ms=5_000, overlap_ms=0,
    )
    assert pipeline.run() == ()
    assert pipeline.run() == ()
    assert calls == [0]


def test_cue_delta_is_recursively_immutable_and_has_stable_identity():
    source = {
        "id": "cue-1", "text": "immutable",
        "evidence": {"tokens": ["a", {"confidence": 0.9}]},
    }
    delta = CueDelta(
        source_path="source.mp4", manifest_key="manifest", backend="fixture",
        chunk_index=2, state="provisional", cues=(source,),
        replacement_mapping={"old": ("cue-1",)},
    )
    source["text"] = "mutated"

    assert delta.cues[0]["text"] == "immutable"
    assert delta.to_payload()["cues"][0]["evidence"]["tokens"][1]["confidence"] == 0.9
    with pytest.raises(TypeError):
        delta.cues[0]["text"] = "changed"
    with pytest.raises(TypeError):
        delta.cues[0]["evidence"]["tokens"][1]["confidence"] = 0.1
    with pytest.raises(TypeError):
        delta.replacement_mapping["old"] = ("other",)
    with pytest.raises(FrozenInstanceError):
        delta.chunk_index = 3


def test_file_cache_identity_changes_for_mtime_size_model_settings_and_renderer(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"one")
    base = CacheIdentity.for_file(
        "fixture", source, settings={"language": "zh"}, model="r1",
        renderer="v1", resolution=(640, 360),
    )
    settings = CacheIdentity.for_file(
        "fixture", source, settings={"language": "en"}, model="r1",
        renderer="v1", resolution=(640, 360),
    )
    model = CacheIdentity.for_file(
        "fixture", source, settings={"language": "zh"}, model="r2",
        renderer="v1", resolution=(640, 360),
    )
    renderer = CacheIdentity.for_file(
        "fixture", source, settings={"language": "zh"}, model="r1",
        renderer="v2", resolution=(1280, 720),
    )
    source.write_bytes(b"different size")
    changed_file = CacheIdentity.for_file(
        "fixture", source, settings={"language": "zh"}, model="r1",
        renderer="v1", resolution=(640, 360),
    )

    assert len({base.key, settings.key, model.key, renderer.key, changed_file.key}) == 5
