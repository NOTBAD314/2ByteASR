from __future__ import annotations

import copy
import os
import threading
import time
from types import MethodType, SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from twobyteasr.caption_design.studio_ai import (
    AIDesignSuggestion,
    request_style_design,
    visual_design_variants,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.caption_design.visual_design_graph import (
    comic_burst_graph,
    glitch_graph,
    streamer_gaming_graph,
)
from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine
from twobyteasr.studio.studio_ui import MpvCanvas, SubtitleStudioPage
from twobyteasr.diagnostics.runtime_trace import RuntimeTraceWriter
from twobyteasr.system.resource_governor import ResourceGovernor, ResourceKind
from twobyteasr.local_models.model_workshop import ModelWorkshopPage
from twobyteasr.rendering.renderer_service import (
    RendererJob,
    RendererRequestHandle,
    RendererService,
    RendererServiceError,
)
from twobyteasr.app.ui import MainWindow
from twobyteasr.playback.waveform_cache import _decode_level0


APP = QApplication.instance() or QApplication([])


def _project(*, evidence_text: str = "") -> SubtitleProject:
    evidence = {"segment:1": {"qwen_asr_text": evidence_text}} if evidence_text else {}
    return SubtitleProject(
        media=StudioMedia(path="D:/fixture.mp4"),
        cues=[StudioCue("cue", 0, 1800, "这是一条用于视觉设计的测试字幕", evidence_refs=["segment:1"])],
        asr_evidence=evidence,
    )


def _valid_design_payload(instruction: str) -> dict:
    variants = [
        graph.to_dict()
        for graph in (streamer_gaming_graph(), comic_burst_graph(), glitch_graph())
    ]
    return {
        "design_intent": "三套可执行的动态字幕方向",
        "visual_changes": ["字体", "色彩", "描边", "动效"],
        "motion_reason": "动态方向使用明确的入场与退出动作",
        "variants": variants,
    }


def test_long_asr_evidence_qc_stays_bounded():
    evidence = "前置邻句" * 30 + "这是一条用于视觉设计的测试字幕" + "后置邻句" * 30
    project = _project(evidence_text=evidence)
    started = time.perf_counter()
    result = SubtitleQCEngine().analyze(project)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5
    assert result is not None


def test_runtime_trace_emit_does_not_wait_for_writer():
    writer = RuntimeTraceWriter(capacity=32, ring_size=32)
    writer_started = threading.Event()

    def slow_writer():
        writer_started.set()
        time.sleep(0.2)

    writer._run = slow_writer  # type: ignore[method-assign]
    started = time.perf_counter()
    for index in range(20):
        writer.emit("TRACE", {"index": index})
    elapsed = time.perf_counter() - started
    assert writer_started.wait(0.2)
    assert elapsed < 0.05
    assert len(writer.recent()) == 20


def test_ai_validation_retry_uses_one_absolute_deadline(monkeypatch):
    instruction = "复古动画"
    responses = [
        {"design_intent": "generic", "visual_changes": [], "motion_reason": "", "variants": []},
        _valid_design_payload(instruction),
    ]
    timeouts: list[float] = []

    class Provider:
        provider_id = "fixture"

        def structured_complete(self, *_args, **kwargs):
            timeouts.append(float(kwargs["timeout"]))
            time.sleep(0.08)
            return copy.deepcopy(responses.pop(0))

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: Provider())
    suggestion = request_style_design(
        _project(), "cue", instruction, {"models": {"polish": "fixture"}}, deadline_seconds=0.3
    )
    assert suggestion.provider_succeeded
    assert len(timeouts) == 2
    assert 0 < timeouts[1] < timeouts[0] - 0.05
    assert timeouts[0] <= 0.301


def test_ai_expired_validation_retry_becomes_typed_fallback(monkeypatch):
    calls = 0

    class Provider:
        provider_id = "fixture"

        def structured_complete(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            time.sleep(0.12)
            return {"design_intent": "generic", "variants": []}

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: Provider())
    suggestion = request_style_design(
        _project(), "cue", "复古动画", {"models": {"polish": "fixture"}}, deadline_seconds=0.1
    )
    assert calls == 1
    assert not suggestion.provider_succeeded
    assert suggestion.provider_error_category == "timeout"
    assert "不表示登录已失效" in suggestion.rationale


def test_ai_uses_configured_model_deadline_without_ui_override(monkeypatch):
    timeouts: list[float] = []

    class Provider:
        provider_id = "fixture"

        def structured_complete(self, *_args, **kwargs):
            timeouts.append(float(kwargs["timeout"]))
            return _valid_design_payload("复古动画")

    monkeypatch.setattr(
        "twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: Provider()
    )
    suggestion = request_style_design(
        _project(),
        "cue",
        "复古动画",
        {"models": {"polish": "fixture", "polish_timeout_seconds": 6.25}},
    )

    assert suggestion.provider_succeeded
    assert len(timeouts) == 1
    assert 6.24 < timeouts[0] <= 6.251


def test_selecting_fallback_variant_preserves_provider_failure():
    visual = visual_design_variants("复古动画")[0]
    source = AIDesignSuggestion(
        "cue",
        visual.to_style_recipe(),
        "Provider failed",
        (visual,),
        raw_response={"provider_error_category": "timeout"},
        provider_succeeded=False,
        provider_error_category="timeout",
        stage_timings_ms={"GENERATING": 100.0},
    )
    owner = SimpleNamespace(
        _preview_visual_recipe=lambda _visual: None,
        _mark_ai_variant_selected=lambda _index: None,
        ai_suggestion_title=SimpleNamespace(setText=lambda _value: None),
        ai_confidence=SimpleNamespace(setText=lambda _value: None),
        ai_preview=SimpleNamespace(setPlainText=lambda _value: None),
    )
    SubtitleStudioPage._select_ai_variant(owner, visual, source)
    assert owner._pending_suggestion.provider_succeeded is False
    assert owner._pending_suggestion.provider_error_category == "timeout"
    assert owner._pending_suggestion.stage_timings_ms == {"GENERATING": 100.0}


def test_close_with_active_asr_hides_before_background_shutdown(monkeypatch):
    calls: list[str] = []

    class Signal:
        def connect(self, callback):
            calls.append(f"connect:{callback.__name__}")

    class Worker:
        finished = Signal()

        def isRunning(self):
            return True

        def requestInterruption(self):
            calls.append("interrupt")

        def terminate(self):
            calls.append("terminate")

    owner = SimpleNamespace(
        worker=Worker(),
        token=SimpleNamespace(cancel=lambda: calls.append("cancel")),
        studio_page=SimpleNamespace(begin_close_page=lambda: calls.append("studio_begin")),
        _studio_close_pending=False,
        _studio_close_finalizing=False,
        hide=lambda: calls.append("hide"),
    )
    owner._worker_close_finished = MethodType(MainWindow._worker_close_finished, owner)
    owner._force_close_worker = MethodType(MainWindow._force_close_worker, owner)
    owner._maybe_finalize_close = MethodType(MainWindow._maybe_finalize_close, owner)
    event = SimpleNamespace(ignore=lambda: calls.append("ignore"), accept=lambda: calls.append("accept"))
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("twobyteasr.app.ui.QTimer.singleShot", lambda *_a, **_k: None)

    started = time.perf_counter()
    MainWindow.closeEvent(owner, event)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1
    assert "cancel" in calls and "interrupt" in calls
    assert calls.index("hide") < calls.index("studio_begin")
    assert "accept" not in calls


def test_paused_seek_trace_requires_frame_seeking_false_and_valid_t8():
    canvas = MpvCanvas()
    generation = canvas.begin_seek_trace(12.0)
    canvas.mark_seek_stage("T5_first_target_frame")
    assert not canvas._finish_seek_trace(generation)
    canvas.mark_seek_stage("T6_seeking_false")
    assert not canvas._finish_seek_trace(generation)
    canvas.mark_seek_stage("T8_active_cue_visual_owner_correct", T8_passed=True)
    assert canvas._finish_seek_trace(generation)
    trace = canvas.seek_latency_traces()[-1]
    assert trace["settled"] is True
    assert "T7_sustained_progression" not in trace["markers"]


def test_playing_seek_trace_cannot_finish_before_sustained_progression():
    canvas = MpvCanvas()
    canvas._paused = False
    generation = canvas.begin_seek_trace(12.0)
    canvas.mark_seek_stage("T5_first_target_frame")
    canvas.mark_seek_stage("T6_seeking_false")
    canvas.mark_seek_stage("T8_active_cue_visual_owner_correct", T8_passed=True)
    assert not canvas._finish_seek_trace(generation)
    assert canvas._active_seek_trace is not None
    canvas.mark_seek_stage("T7_sustained_progression")
    assert canvas._finish_seek_trace(generation)
    trace = canvas.seek_latency_traces()[-1]
    assert trace["seek_was_paused"] is False
    assert trace["settled"] is True
    assert trace["elapsed_ms"]["T7_sustained_progression"] <= trace["elapsed_ms"]["T9_event_loop_settled"]


def test_seek_settlement_expires_without_touching_widgets_during_close():
    expired: list[tuple[int, str]] = []
    owner = SimpleNamespace(
        _close_requested=True,
        video=SimpleNamespace(
            _active_seek_trace={"generation": 17},
            _expire_seek_trace=lambda generation, reason: expired.append(
                (generation, reason)
            ),
        ),
        subtitle_visibility_trace=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("closing settlement inspected deleted widgets")
        ),
    )

    SubtitleStudioPage._schedule_seek_trace_settlement(owner, attempt=1)

    assert expired == [(17, "page closing")]


def test_late_ass_callbacks_cannot_restart_compiler_after_close():
    owner = SimpleNamespace(
        _close_requested=True,
        project=object(),
        _ass_actor=None,
        _ass_worker_running=True,
        _preview_timer=SimpleNamespace(
            start=lambda: (_ for _ in ()).throw(
                AssertionError("closing page restarted ASS preview")
            )
        ),
    )

    SubtitleStudioPage._start_ass_worker(owner, 8)
    SubtitleStudioPage._ass_ready(owner, 7, "ignored.ass")

    assert owner._ass_actor is None
    assert owner._ass_worker_running is False


def test_motion_replay_uses_page_seek_coordinator():
    seeks: list[float] = []
    paused: list[bool] = []
    owner = SimpleNamespace(
        _cue_lookup={"cue": SimpleNamespace(start_ms=1_000, end_ms=1_800)},
        selected_cue_id="cue",
        video=SimpleNamespace(
            controller=object(),
            _paused=False,
            set_paused=lambda value: paused.append(bool(value)),
        ),
        _seek=lambda seconds: seeks.append(float(seconds)),
        _sync_play_button=lambda _paused: None,
        _show_video_error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
    )

    SubtitleStudioPage._replay_motion(owner)

    assert seeks == [0.92]
    assert paused == [False]


def test_formal_save_autosave_wait_is_bounded():
    release = threading.Event()
    worker = threading.Thread(target=lambda: release.wait(1.0), daemon=True)
    worker.start()
    owner = SimpleNamespace(_autosave_thread=worker)
    started = time.perf_counter()

    with pytest.raises(TimeoutError, match="自动保存仍在写入"):
        SubtitleStudioPage._wait_for_autosave_worker(owner, timeout=0.01)

    assert time.perf_counter() - started < 0.1
    release.set()


def test_model_workshop_temp_cleanup_never_scans_on_gui_thread(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    calls: list[set[str]] = []

    def blocking_cleanup(_root, active):
        calls.append(set(active))
        started.set()
        release.wait(1.0)

    monkeypatch.setattr(
        "twobyteasr.local_models.model_workshop.cleanup_orphan_download_temps",
        blocking_cleanup,
    )
    owner = SimpleNamespace(
        root=tmp_path,
        isVisible=lambda:True,
        _download_dialogs=[],
        _temp_cleanup_lock=threading.Lock(),
        _temp_cleanup_running=False,
    )
    caller = threading.get_ident()
    started_at = time.perf_counter()

    ModelWorkshopPage._periodic_temp_cleanup(owner)
    ModelWorkshopPage._periodic_temp_cleanup(owner)

    assert time.perf_counter() - started_at < 0.05
    assert started.wait(0.5)
    assert calls == [set()]
    assert all(thread.ident != caller for thread in threading.enumerate() if thread.name == "model-workshop-temp-cleanup")
    release.set()


def test_waveform_decode_cancellation_interrupts_blocked_stdout(monkeypatch, tmp_path):
    release = threading.Event()

    class BlockingStdout:
        def read(self, _size):
            release.wait(2.0)
            return b""

    class EmptyStderr:
        @staticmethod
        def read():
            return b""

    class FakeProcess:
        stdout = BlockingStdout()
        stderr = EmptyStderr()

        def __init__(self):
            self.returncode = None
            self.killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9
            release.set()

        def wait(self, timeout=None):
            assert timeout is None or timeout <= 1.0
            release.wait(timeout)
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(
        "twobyteasr.playback.waveform_cache.popen_hidden_subprocess",
        lambda *_args, **_kwargs: process,
    )
    cancelled = threading.Event()
    timer = threading.Timer(0.05, cancelled.set)
    timer.start()
    started = time.perf_counter()

    with pytest.raises(InterruptedError, match="cancelled"):
        _decode_level0(
            tmp_path / "fixture.flv",
            tmp_path / "ffmpeg.exe",
            tmp_path / "waveform.f32",
            cancelled=cancelled.is_set,
        )

    timer.cancel()
    assert time.perf_counter() - started < 0.5
    assert process.killed


def test_renderer_shutdown_wakes_pending_request(tmp_path):
    class Stdin:
        writes: list[str] = []

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            pass

    class Process:
        pid = 123
        stdin = Stdin()

        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    service = RendererService(tmp_path)
    process = Process()
    service._process = process
    handle = RendererRequestHandle(service, "pending", 1)
    service._pending[handle.request_id] = handle

    service.shutdown(timeout=0.1)

    assert handle._event.is_set()
    assert isinstance(handle._error, RendererServiceError)
    assert service.process_id is None
    assert service._pending == {}


def test_renderer_does_not_retry_across_shutdown_generation(tmp_path, monkeypatch):
    service = RendererService(tmp_path)
    restarts: list[str] = []

    class Handle:
        def result(self, _timeout):
            service._shutdown_generation += 1
            raise RendererServiceError("renderer service shut down")

    monkeypatch.setattr(service, "submit", lambda *_args, **_kwargs: Handle())
    monkeypatch.setattr(
        service, "restart", lambda *, reason: restarts.append(reason)
    )

    with pytest.raises(RendererServiceError, match="shut down"):
        service.render(
            [RendererJob(str(tmp_path / "frame.png"), {}, 0)],
            timeout=0.1,
        )

    assert restarts == []


def test_playback_allows_one_ai_and_foreground_fidelity_but_yields_refinement():
    governor = ResourceGovernor(background_limit=2)
    governor.set_playback(True)
    assert governor.should_yield(ResourceKind.AI) is False
    assert governor.should_yield(ResourceKind.WAVEFORM) is True
    assert governor.should_yield(ResourceKind.PROXY) is True
    assert governor.should_yield(ResourceKind.ADVANCED_PREVIEW) is True
    assert governor.should_yield(
        ResourceKind.ADVANCED_PREVIEW, foreground=True,
    ) is False

    with governor.lease(ResourceKind.AI) as ai_allowed:
        assert ai_allowed is True
        assert governor.should_yield(ResourceKind.AI) is True
        with governor.lease(
            ResourceKind.ADVANCED_PREVIEW, foreground=True,
        ) as fidelity_allowed:
            assert fidelity_allowed is True
            snapshot = governor.snapshot()
            assert snapshot.active == {"ADVANCED_PREVIEW": 1, "AI": 1}
            assert snapshot.foreground_active == {"ADVANCED_PREVIEW": 1}
