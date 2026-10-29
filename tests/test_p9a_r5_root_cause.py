"""P9A-R5 regressions for persisted AI config and delayed seek audio."""

from __future__ import annotations

import copy
import json
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.app import ui
from twobyteasr.providers.ai_providers import AIProviderError, AntigravityCLIProvider
from twobyteasr.playback.audio_engine import (
    _PcmRingDevice,
    decoder_restart_required,
    trim_startup_pcm,
)
from twobyteasr.providers.llm_config import active_service_values
from twobyteasr.acceptance.p74d_runtime_audit import lifecycle_events_since
from twobyteasr.acceptance.p9a_r1_packaged_audit import audio_sample_matches_target
from twobyteasr.playback.studio_mpv import mpv_startup_arguments
from twobyteasr.caption_design.studio_ai import _provider_failure_message
from twobyteasr.studio.studio_ui import MpvCanvas


def _app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    ("service", "provider", "transport", "base_url", "model"),
    [
        (
            "deepseek",
            "deepseek",
            "openai_compatible",
            "https://api.deepseek.com/v1",
            "deepseek-v4-flash",
        ),
        (
            "antigravity",
            "google_antigravity",
            "antigravity_cli",
            "",
            "gemini-3.7-flash-high",
        ),
        (
            "custom",
            "custom",
            "openai_compatible",
            "https://openai-compatible.example/v1",
            "fixture-model",
        ),
    ],
)
def test_ai_config_save_reopen_and_recognition_start_is_offline(
    tmp_path,
    monkeypatch,
    service,
    provider,
    transport,
    base_url,
    model,
):
    settings_path = tmp_path / "settings.json"
    configure_calls = []

    class Legacy:
        def __init__(self, settings=None):
            self.RUNTIME_SETTINGS = settings or {"models": {}, "switches": {}}

        def configure_runtime_llms(self, models, **kwargs):
            configure_calls.append((copy.deepcopy(models), dict(kwargs)))
            persisted = copy.deepcopy(self.RUNTIME_SETTINGS)
            persisted.setdefault("models", {}).update(copy.deepcopy(models))
            persisted.setdefault("switches", {}).update({
                "unified_glm_processing": bool(kwargs["unified_glm_processing"]),
                "use_ai_grouping": bool(kwargs["use_ai_grouping"]),
            })
            self.RUNTIME_SETTINGS = persisted
            settings_path.write_text(
                json.dumps(persisted, ensure_ascii=False), encoding="utf-8"
            )

    def network_forbidden(*_args, **_kwargs):
        raise AssertionError("saving AI configuration must not make a live request")

    monkeypatch.setattr(ui, "read_api_key", lambda *_args: ("stored-key", "DPAPI"))
    monkeypatch.setattr(ui, "resolve_api_key", lambda *_args: ("stored-key", "DPAPI"))
    monkeypatch.setattr(ui, "save_api_key_for", lambda *_args: None)
    monkeypatch.setattr(ui, "fetch_openai_compatible_models", network_forbidden)
    monkeypatch.setattr(ui, "run_llm_json_self_test", network_forbidden)
    monkeypatch.setattr(ui.GLOBAL_PROVIDER_REGISTRY, "bind", lambda *_args: None)

    values = {
        "service": service,
        "provider": provider,
        "transport": transport,
        "protocol": "auto",
        "base_url": base_url,
        "model": model,
        "key": "",
    }
    first = Legacy()
    saved = ui.persist_ai_configuration(
        first,
        values,
        values,
        unified=False,
        share_key=False,
        require_ready=False,
        use_ai_grouping=False,
    )
    assert saved["missing_keys"] == ()

    reopened_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    reopened = Legacy(reopened_settings)
    active = active_service_values(reopened.RUNTIME_SETTINGS)
    assert active["service"] == service
    assert active["provider"] == provider
    assert active["transport"] == transport
    assert active["base_url"] == base_url
    assert active["model"] == model

    recognition_values = {**active, "key": ""}
    started = ui.persist_ai_configuration(
        reopened,
        recognition_values,
        recognition_values,
        unified=False,
        share_key=False,
        require_ready=True,
        use_ai_grouping=False,
    )
    assert started["missing_keys"] == ()
    assert len(configure_calls) == 2


def test_delayed_decoder_drift_cannot_restart_before_first_pcm():
    for drift_ms in (350.0, 800.0, 1_700.0, 2_400.0):
        assert not decoder_restart_required(
            process_alive=True,
            same_source=True,
            same_rate=True,
            drift_ms=drift_ms,
            paused=False,
            previous_drift_ms=drift_ms,
            decoder_ready=False,
        )
    assert decoder_restart_required(
        process_alive=True,
        same_source=True,
        same_rate=True,
        drift_ms=1_700.0,
        paused=False,
        previous_drift_ms=1_700.0,
        decoder_ready=True,
    )


def test_audio_ahead_drift_never_restarts_at_an_earlier_requested_position():
    healthy = dict(process_alive=True, same_source=True, same_rate=True)
    for drift_ms, previous_drift_ms in ((-350.0, -340.0), (-900.0, -900.0)):
        assert decoder_restart_required(
            **healthy,
            drift_ms=drift_ms,
            paused=False,
            previous_drift_ms=previous_drift_ms,
            decoder_ready=True,
        ) is False


def test_decoder_readiness_is_reset_with_each_ring_generation():
    device = _PcmRingDevice()
    try:
        assert device.has_produced_pcm() is False
        assert not decoder_restart_required(
            process_alive=True,
            same_source=True,
            same_rate=True,
            drift_ms=1_700.0,
            paused=False,
            previous_drift_ms=1_700.0,
            decoder_ready=device.has_produced_pcm(),
        )

        generation = device._generation
        assert device.append(b"\x01\x00" * 2_048, generation, threading.Event())
        assert device.has_produced_pcm() is True
        assert decoder_restart_required(
            process_alive=True,
            same_source=True,
            same_rate=True,
            drift_ms=1_700.0,
            paused=False,
            previous_drift_ms=1_700.0,
            decoder_ready=device.has_produced_pcm(),
        )

        device.reset_stream()
        assert device.has_produced_pcm() is False
    finally:
        device.close()


def test_first_pcm_metadata_snapshot_is_generation_scoped_and_zero_is_valid():
    device = _PcmRingDevice()
    try:
        generation = device.reset_stream()
        assert device.source_start_snapshot() == (generation, None)
        assert device.append(
            b"\x00\x00" * 2_048,
            generation,
            threading.Event(),
            source_start_ms=0.0,
        )
        assert device.source_start_snapshot() == (generation, 0.0)

        next_generation = device.reset_stream()
        assert next_generation > generation
        assert device.source_start_snapshot() == (next_generation, None)
        assert not device.append(
            b"\x00\x00" * 2_048,
            generation,
            threading.Event(),
            source_start_ms=12_345.0,
        )
    finally:
        device.close()


def test_sync_before_sink_prebuffer_cannot_arm_drift_restart():
    device = _PcmRingDevice()
    try:
        generation = device.reset_stream()
        assert device.source_start_snapshot() == (generation, None)
        # The feeder may have produced PCM while the queued wakeup is still
        # pending.  Until the sink crosses its prebuffer gate this is not a
        # steady-state decoder-ready sample.
        assert device.append(
            b"\x01\x00" * 2_048,
            generation,
            threading.Event(),
            source_start_ms=3_600_000.0,
        )
        assert device.source_start_snapshot() == (generation, 3_600_000.0)
        assert not decoder_restart_required(
            process_alive=True,
            same_source=True,
            same_rate=True,
            drift_ms=-900.0,
            paused=False,
            previous_drift_ms=-900.0,
            # queued wakeup has not started the sink yet
            decoder_ready=False,
        )
    finally:
        device.close()


def test_delayed_decoder_discards_startup_lag_on_pcm_frame_boundary():
    payload = bytes(19_200)  # 100 ms of stereo s16le at 48 kHz.
    retained, retained_source_ms = trim_startup_pcm(
        payload,
        chunk_source_ms=3_600_000.0,
        requested_source_ms=3_600_075.0,
        effective_rate=1.0,
        bytes_per_second=192_000,
        bytes_per_frame=4,
    )
    assert len(retained) == 4_800
    assert retained_source_ms == pytest.approx(3_600_075.0)
    assert len(retained) % 4 == 0

    discarded, next_source_ms = trim_startup_pcm(
        payload,
        chunk_source_ms=3_600_000.0,
        requested_source_ms=3_601_700.0,
        effective_rate=1.0,
        bytes_per_second=192_000,
        bytes_per_frame=4,
    )
    assert discarded == b""
    assert next_source_ms == pytest.approx(3_600_100.0)


def test_packaged_audio_audit_rejects_pre_seek_buffered_pcm():
    stale = {
        "source_generation": 8,
        "decoder_command_start_ms": 0,
        "requested_source_ms": 3_600_000,
        "decoded_bytes": 262_144,
        "sink_consumed_bytes": 60_288,
    }
    target = {
        **stale,
        "source_generation": 9,
        "decoder_command_start_ms": 3_600_000,
    }

    assert not audio_sample_matches_target(
        stale, prior_generation=8, target_ms=3_600_000
    )
    assert audio_sample_matches_target(
        target, prior_generation=8, target_ms=3_600_000
    )


def test_packaged_audio_audit_accepts_delayed_first_pcm_after_clock_advances():
    delayed = {
        "source_generation": 9,
        "decoder_command_start_ms": 3_600_000,
        "requested_source_ms": 3_601_700,
        "decoded_bytes": 16_384,
        "sink_consumed_bytes": 0,
    }
    assert audio_sample_matches_target(
        delayed, prior_generation=8, target_ms=3_600_000
    )


def test_overlay_lifecycle_traces_create_update_and_rejects_active_remove(tmp_path):
    _app()
    records = []

    class Page(QWidget):
        def _studio_trace(self, event, **fields):
            records.append((event, fields))

    class Controller:
        running = True

        def post_raw_overlay(self, *_args, **_kwargs):
            return True

        def post_remove_overlay(self, *_args, **_kwargs):
            return True

    page = Page()
    canvas = MpvCanvas(page)
    canvas.controller = Controller()
    canvas._media_attached = True  # explicit live-media precondition
    canvas._compositor_overlay_dir = tmp_path / "overlays"
    image = QImage(16, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("#FFFFFFFF"))
    context = {
        "cue_id": "cue-r5",
        "renderer_path": "VISUAL_GRAPH",
        "caller": "fixture",
        "reason": "playback_refresh",
        "cue_active": True,
        "scene_alive": True,
        "opacity": 1.0,
        "scene_id": "scene-r5",
        "visualGraph_hash": "graph-r5",
    }

    assert canvas.publish_compositor_overlay(
        0, image, QRect(0, 0, 160, 80), source_bounds=image.rect(), context=context
    )
    assert canvas.publish_compositor_overlay(
        0, image, QRect(1, 0, 160, 80), source_bounds=image.rect(), context=context
    )
    assert not canvas.remove_compositor_overlay(0, context=context)
    assert canvas.active_compositor_overlay_ids() == [0]

    lifecycle = [fields for event, fields in records if event == "COMPOSITOR_OVERLAY_LIFECYCLE"]
    assert [item["action"] for item in lifecycle] == ["CREATE", "UPDATE", "REMOVE_REJECTED"]
    assert lifecycle[-1]["cue_id"] == "cue-r5"
    assert lifecycle[-1]["paused"] is True
    assert "test_overlay_lifecycle" in lifecycle[-1]["call_stack"]

    assert canvas.remove_compositor_overlay(0, context={**context, "cue_active": False})
    assert records[-1][1]["action"] == "REMOVE"
    canvas.deleteLater()
    page.deleteLater()


def test_overlay_lifecycle_audit_preserves_zero_overlay_id():
    records = [
        {
            "event": "COMPOSITOR_OVERLAY_LIFECYCLE",
            "overlay_id": 0,
            "time_monotonic": 20.0,
            "action": "REMOVE",
        },
        {
            "event": "COMPOSITOR_OVERLAY_LIFECYCLE",
            "overlay_id": 1,
            "time_monotonic": 20.0,
            "action": "REMOVE",
        },
    ]

    assert lifecycle_events_since(
        records, overlay_id=0, started_monotonic=19.0
    ) == [records[0]]


def test_media_startup_waits_for_clock_and_frame_then_releases_playback():
    _app()

    class Controller:
        running = True

        def __init__(self):
            self.frame = {}
            self.pause_requests = []
            self.sequence = 0

        def observed_properties(self):
            return {
                "duration": 10.0,
                "pause": True,
                "speed": 1.0,
                "eof-reached": False,
                "idle-active": False,
                "seeking": False,
                "time-pos": 0.04,
                "video-out-params": {"dw": 1920, "dh": 1080},
                "video-frame-info": dict(self.frame),
                "video-codec": "h264",
                "hwdec-current": "d3d11va",
                "hwdec-interop": "d3d11-egl",
            }

        def observed_position(self):
            self.sequence += 1
            return {
                "position": 0.04,
                "source_generation": 0,
                "actor_sequence": self.sequence,
                "observed_monotonic_ts": __import__("time").monotonic(),
                "source": "property_change",
            }

        def post_set_paused(self, paused):
            self.pause_requests.append(bool(paused))
            return True

    controller = Controller()
    canvas = MpvCanvas()
    canvas.controller = controller
    canvas._startup_state = "MEDIA_OPENING"
    canvas._startup_play_requested = True
    canvas._startup_started_at = __import__("time").perf_counter()

    canvas._reconcile_position()
    assert canvas.startup_state_snapshot()["state"] == "CLOCK_SYNCING"
    assert controller.pause_requests == []
    assert canvas._paused is True

    controller.frame = {"pts": 0.04, "picture-type": "I"}
    canvas._reconcile_position()
    assert canvas.startup_state_snapshot()["state"] == "READY"
    _app().processEvents()  # Startup posts the ordinary PCM/frame readiness gate.
    assert controller.pause_requests == [False]
    assert canvas._paused is False
    assert canvas._last_hwdec_snapshot == {
        "codec": "h264",
        "requested": "auto-safe",
        "selected": "d3d11va",
        "interop": "d3d11-egl",
        "software_fallback": False,
    }
    canvas.deleteLater()


def test_mpv_requests_windows_gpu_path_but_keeps_runtime_selection_observable():
    command = mpv_startup_arguments("mpv.exe", 123, r"\\.\pipe\fixture")
    assert "--hwdec=auto-safe" in command
    assert "--vo=gpu-next" in command
    assert "--gpu-api=d3d11" in command


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("nonzero_exit", "PROCESS"),
        ("timeout", "TIMEOUT"),
        ("empty_response", "EMPTY_OUTPUT"),
        ("structured_json_parse_error", "JSON"),
        ("schema", "SCHEMA"),
        ("quality_validator", "QUALITY"),
    ],
)
def test_generate_failure_category_is_exact(category, expected):
    error = AIProviderError("fixture", category=category)
    assert _provider_failure_message(error)[3] == expected


def test_antigravity_process_trace_records_execution_contract(monkeypatch):
    class Process:
        returncode = 0
        pid = 123
        def __init__(self):
            from io import StringIO
            self.stdout=StringIO('{"event":"result","result":{"status":"SUCCESS","response":"2ByteASR_OK"}}\n')
            self.stderr=StringIO('')
            self.stdin=StringIO()

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def communicate(*_args, **_kwargs):
            return '{"response":"2ByteASR_OK"}', ""

    monkeypatch.setattr(
        "twobyteasr.providers.ai_providers.popen_hidden_subprocess",
        lambda *_args, **_kwargs: Process(),
    )
    provider = AntigravityCLIProvider(executable="agy.exe")
    assert provider.complete([{"role": "user", "content": "secret prompt"}], timeout=42.0) == "2ByteASR_OK"
    trace = provider.last_invocation_trace
    assert trace["purpose"] == "Antigravity CLI streaming request"
    assert "-p" not in trace["command"]
    assert trace["request_budget"]["transport"] == "official_stdin_ndjson"
    assert "secret prompt" not in json.dumps(trace)
    assert trace["working_directory"]
    assert trace["timeout_seconds"] == 42.0
    assert trace["exit_code"] == 0
    assert trace["stdout_size"] > 0
    assert trace["stderr_size"] == 0
