import json
import os
import threading
import time
from types import MethodType, SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.rendering.advanced_renderer import compile_composition_data
from twobyteasr.rendering.ass_compile_actor import AssCompileActor, AssCompileResult
from twobyteasr.rendering.ass_compiler import compile_ass, compile_ass_revision
from twobyteasr.playback.studio_mpv import MpvIPCTimeoutError, _MpvCommandActor
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    save_autosave_revision,
)
from twobyteasr.projects.studio_revisions import (
    StudioRevisionStore,
    preview_render_revision,
)
from twobyteasr.projects.studio_runtime_state import DirtyDomain, StateDelta
from twobyteasr.studio.studio_ui import AdvancedLiveCanvas, SubtitlePositionOverlay
from twobyteasr.caption_style.style_recipe import FillSpec, normalize_shadow_contract


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project() -> SubtitleProject:
    project = SubtitleProject(
        media=StudioMedia(
            path="D:/fixture.mp4", duration_ms=4_000,
            width=1920, height=1080,
        ),
        cues=[
            StudioCue(id="cue-1", start_ms=0, end_ms=1_900, text="ONE"),
            StudioCue(id="cue-2", start_ms=2_000, end_ms=3_900, text="TWO"),
        ],
    )
    project.validate()
    return project


def _delta(revision: int, dirty: DirtyDomain, *cue_ids: str) -> StateDelta:
    return StateDelta(
        action_id=f"p71c-{revision}",
        dirty=dirty,
        affected_cue_ids=frozenset(cue_ids),
        affected_sequence_ids=frozenset(),
        affected_ranges=(),
        selection_before="",
        selection_after="",
        revision=revision,
    )


def test_render_revision_compiles_with_project_parity_and_shares_unchanged_cues():
    project = _project()
    store = StudioRevisionStore(project)
    before = store.render

    assert compile_ass_revision(before) == compile_ass(project)

    project.cues[0].text = "ONE EDITED"
    store.consume(_delta(
        1,
        DirtyDomain.CUE_CONTENT | DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.AUTOSAVE,
        "cue-1",
    ))
    after = store.render

    assert after.cues[0].text == "ONE EDITED"
    assert after.cues[1] is before.cues[1]
    assert after.styles is before.styles
    assert after.visual_revision == before.visual_revision + 1
    assert compile_ass_revision(after) == compile_ass(project)


def test_preview_revision_has_content_identity_and_preserves_unset_positions():
    revision = StudioRevisionStore(_project()).render
    derived = preview_render_revision(
        revision,
        transform_overrides={
            "cue-1": {"font_size": 72.0},
            "cue-2": {"position_x": 320},
        },
    )
    repeated = preview_render_revision(
        revision,
        transform_overrides={
            "cue-1": {"font_size": 72.0},
            "cue-2": {"position_x": 320},
        },
    )
    changed = preview_render_revision(
        revision,
        transform_overrides={"cue-1": {"font_size": 73.0}},
    )

    styles = {style.id: style for style in derived.styles}
    first = styles[derived.cues[0].style_id]
    second = styles[derived.cues[1].style_id]
    assert first.id != second.id
    assert (first.position_x, first.position_y) == (None, None)
    assert (second.position_x, second.position_y) == (320, None)
    assert derived.compile_key == repeated.compile_key
    assert derived.compile_key != revision.compile_key
    assert changed.compile_key != derived.compile_key


def test_persistence_revision_does_not_observe_later_live_mutation(tmp_path):
    project = _project()
    store = StudioRevisionStore(project)
    revision = store.refresh_persistence(7)
    project.cues[0].text = "MUTATED AFTER SNAPSHOT"
    project.studio_state["playhead_ms"] = 999

    target, phases = save_autosave_revision(
        revision,
        tmp_path / "source.2byteproj",
        base=tmp_path,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["cues"][0]["text"] == "ONE"
    assert payload["studio_state"].get("playhead_ms") != 999
    assert set(phases) >= {
        "materialize_ms", "serialize_ms", "persist_ms", "fsync_ms",
    }


def test_ass_actor_uses_spawned_process_cache_and_recovers_after_exit():
    revision = StudioRevisionStore(_project()).render
    ready: list[AssCompileResult] = []
    failed: list[tuple[int, str]] = []
    actor = AssCompileActor(ready.append, lambda generation, message: failed.append((generation, message)))
    try:
        actor.submit(1, revision)
        assert actor.wait_idle(20)
        assert failed == []
        assert ready[-1].content == compile_ass_revision(revision)
        first_pid = ready[-1].process_id
        assert first_pid > 0

        actor.submit(2, revision)
        assert actor.wait_idle(5)
        assert ready[-1].cache_hit is True
        assert ready[-1].process_id == first_pid

        process = actor._process
        assert process is not None
        process.terminate()
        process.join(timeout=5)
        updated = preview_render_revision(revision, text_overrides={"cue-1": "LATEST"})
        actor.submit(3, updated)
        assert actor.wait_idle(20)
        assert failed == []
        assert ready[-1].process_id > 0
        assert ready[-1].process_id != first_pid
        assert "LATEST" in ready[-1].content
        assert actor.restart_count == 1
    finally:
        actor.close()
    assert not actor._thread.is_alive()


def test_ass_actor_drops_intermediate_pending_revisions():
    revision = StudioRevisionStore(_project()).render
    started = threading.Event()
    ready: list[int] = []
    actor = AssCompileActor(lambda result: ready.append(result.generation), lambda *_args: None)

    def slow_compile(_self, generation, value):
        if generation == 1:
            started.set()
            time.sleep(0.08)
        return AssCompileResult(generation, value, f"generation={generation}", 0.0)

    actor._compile = MethodType(slow_compile, actor)
    try:
        actor.submit(1, revision)
        assert started.wait(2)
        actor.submit(2, preview_render_revision(revision, text_overrides={"cue-1": "TWO"}))
        actor.submit(3, preview_render_revision(revision, text_overrides={"cue-1": "THREE"}))
        assert actor.wait_idle(5)
        assert ready == [3]
    finally:
        actor.close()


def test_advanced_preview_worker_is_serial_and_latest_wins():
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SimpleNamespace()
    page._queue_advanced_preview_job = MethodType(
        SubtitleStudioPage._queue_advanced_preview_job, page,
    )
    page._advanced_preview_worker = MethodType(
        SubtitleStudioPage._advanced_preview_worker, page,
    )
    page._wait_advanced_preview_idle = MethodType(
        SubtitleStudioPage._wait_advanced_preview_idle, page,
    )
    page._advanced_preview_condition = threading.Condition()
    page._advanced_preview_pending_job = None
    page._advanced_preview_worker_running = False
    page._advanced_preview_worker_stopping = False
    page._advanced_preview_thread = None
    page._advanced_render_lock = threading.Lock()
    page._advanced_preview_publish_queue = __import__("queue").SimpleQueue()
    page._advanced_preview_state = SimpleNamespace(generation=1)
    page._studio_trace = lambda *_args, **_kwargs: None
    # P9B 起的 worker 契约：resource governor 租约、runtime cache 记录、
    # identity.job_kind 前台判定——骨架提供等价假件，不触全局单例。
    class _RuntimeCache:
        def get_or_create(self, _key, produce, store_memory=False):
            return produce(), None

        def register_artifact(self, *_args, **_kwargs):
            return None

    page._runtime_cache = _RuntimeCache()

    class _Governor:
        class _Lease:
            def __enter__(self):
                return True

            def __exit__(self, *_args):
                return False

        def lease(self, *_args, **_kwargs):
            return _Governor._Lease()

    page._resource_governor = _Governor()

    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    class Cache:
        @staticmethod
        def render_snapshot(snapshot, **_kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                calls.append(snapshot.text)
                if snapshot.text == "first":
                    first_started.set()
                    assert release_first.wait(3)
                time.sleep(0.02)
                return snapshot.text, f"{snapshot.text}.png", False
            finally:
                with active_lock:
                    active -= 1

        @staticmethod
        def discard_if_stale(generation, current):
            return generation != current

    page._advanced_preview_cache = Cache()
    identity = SimpleNamespace(cue_id="cue", request_key="key", job_kind="production")
    page._queue_advanced_preview_job(
        identity, 1, SimpleNamespace(text="first"), False, 300, 640, 360,
        "cue", "first",
    )
    assert first_started.wait(2)
    page._advanced_preview_state.generation = 2
    page._queue_advanced_preview_job(
        identity, 2, SimpleNamespace(text="middle"), False, 300, 640, 360,
        "cue", "middle",
    )
    page._advanced_preview_state.generation = 3
    page._queue_advanced_preview_job(
        identity, 3, SimpleNamespace(text="latest"), False, 300, 640, 360,
        "cue", "latest",
    )
    release_first.set()
    assert page._wait_advanced_preview_idle(5)
    with page._advanced_preview_condition:
        page._advanced_preview_worker_stopping = True
        page._advanced_preview_condition.notify_all()
    page._advanced_preview_thread.join(timeout=2)

    assert calls == ["first", "latest"]
    assert max_active == 1
    kind, _identity, generation, path, _hit = page._advanced_preview_publish_queue.get_nowait()
    assert (kind, generation, path) == ("ready", 3, "latest.png")


def test_transform_visual_has_transparent_interior_and_live_handles(app):
    overlay = SubtitlePositionOverlay()
    overlay.resize(900, 520)
    overlay.set_text("Transform transparent")
    overlay.set_font_size(64)
    image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    overlay._draw_transform_visual(painter)
    painter.end()

    rect = overlay._subtitle_rect()
    interior = QPoint(
        round(rect.left() + rect.width() * 0.25),
        round(rect.center().y()),
    )
    assert rect.contains(interior)
    assert image.pixelColor(interior).alpha() == 0
    assert overlay._handle_at(rect.bottomRight().toPoint()) == "br"
    edge_alpha = max(
        image.pixelColor(round(rect.left()) + offset, round(rect.center().y())).alpha()
        for offset in range(-3, 4)
    )
    assert edge_alpha > 0


def test_gradient_motion_none_is_static_but_explicit_motion_changes(app):
    owner = QWidget()
    canvas = AdvancedLiveCanvas(owner)
    canvas._source = QPixmap(320, 120)
    canvas._source.fill(QColor("#FFFFE45E"))
    canvas.set_base_geometry(QRect(10, 20, 320, 120))
    canvas._snapshot = SimpleNamespace(
        motion_recipe={"mode": "none"}, start_ms=0, end_ms=1_000,
    )
    states = []
    for sample in (10, 500, 990):
        canvas.sync_time(sample, paused=False)
        states.append((canvas.geometry().getRect(), canvas._display_opacity))
    assert states[0] == states[1] == states[2] == ((10, 20, 320, 120), 1.0)

    canvas._last_frame_signature = None
    canvas._snapshot = SimpleNamespace(
        motion_recipe={
            "mode": "explicit",
            "entrance": {"type": "fade", "duration_ms": 200},
            "exit": {"type": "fade", "duration_ms": 200},
        },
        start_ms=0,
        end_ms=1_000,
    )
    canvas.sync_time(10)
    assert canvas._compiled_scene is not None
    # P9A-R3: fades live inside the shared graph compiler's sampled opacity,
    # not in the widget-level display opacity (which stays 1.0 in graph mode).
    early = canvas._compiled_scene.sample(10).value("group", "opacity")
    canvas.sync_time(500)
    middle = canvas._compiled_scene.sample(500).value("group", "opacity")
    canvas.sync_time(990)
    late = canvas._compiled_scene.sample(990).value("group", "opacity")
    assert early < middle
    assert late < middle


@pytest.mark.parametrize("strength", [0.0, 0.1, 0.5, 1.0])
def test_shadow_strength_has_stable_canonical_semantics(strength):
    shadow = normalize_shadow_contract(strength)
    assert shadow["enabled"] is (strength > 0)
    assert shadow["color"] == "#FF000000"
    assert shadow["opacity"] == pytest.approx(min(0.78, strength * 0.24))
    assert shadow["offset_x"] == pytest.approx(strength)
    assert shadow["offset_y"] == pytest.approx(strength)
    assert shadow["blur"] == pytest.approx(strength * 1.5)
    assert shadow["spread"] == 0.0


def test_legacy_shadow_alpha_and_gradient_motion_compile_to_explicit_contract():
    legacy = normalize_shadow_contract({
        "color": "#80120A08", "offsetX": 5, "offsetY": 3, "blur": 2,
    })
    assert legacy["enabled"] is True
    assert legacy["color"] == "#FF120A08"
    assert legacy["opacity"] == pytest.approx(0x80 / 255)

    project = _project()
    # 现行契约：描边层数派生自工程样式（outline2_width>0 才有第二层）；
    # recipe.outline.layers 是下游快照产物，不反向驱动层数。
    _style = next(s for s in project.styles if s.id == project.cues[0].style_id)
    _style.outline_color = "#FFFFFFFF"
    _style.outline_width = 5.0
    _style.outline2_color = "#FF101317"
    _style.outline2_width = 2.0
    project.style_recipes["gradient"] = {
        "name": "Static gradient shadow",
        "engine": "remotion",
        "colors": {"fill": FillSpec.linear([
            {"color": "#FFFFE45E", "position": 0.0},
            {"color": "#FF20D9FF", "position": 1.0},
        ]).to_dict()},
        "outline": {
            "layers": [
                {"color": "#FFFFFFFF", "width": 5},
                {"color": "#FF101317", "width": 2},
            ],
            "shadow": 0.5,
        },
        "motion": {},
    }
    project.cues[0].style_id = "gradient"
    payload = compile_composition_data(
        project, width=1920, height=1080, fps=30,
        start_seconds=0, duration_seconds=1.9,
    )
    visual = payload["recipes"]["gradient"]
    assert visual["motion"]["mode"] == "none"
    assert visual["motion"].get("origin", "none") == "none"
    assert visual["fill"]["type"] == "gradient"
    assert len(visual["strokes"]) == 2
    assert visual["shadow"] == {
        "enabled": True,
        "color": "#000000FF",
        "opacity": pytest.approx(0.12),
        "offsetX": 0.5,
        "offsetY": 0.5,
        "blur": 0.75,
        "spread": 0.0,
    }


def test_mpv_pipe_read_is_bounded_and_reconnect_is_single_retry(tmp_path):
    read_fd, write_fd = os.pipe()
    read_pipe = os.fdopen(read_fd, "rb", buffering=0)
    try:
        actor = object.__new__(_MpvCommandActor)
        actor._pipe = read_pipe
        actor._read_buffer = b""
        actor._stopping = False
        with pytest.raises(MpvIPCTimeoutError):
            actor._readline_with_timeout(0.03)
    finally:
        read_pipe.close()
        os.close(write_fd)

    actor = object.__new__(_MpvCommandActor)
    actor.controller = SimpleNamespace(running=True)
    actor._thread = threading.current_thread()
    actor._stopping = False
    actor._degraded = False
    actor._last_error = ""
    actor._reconnect_attempts = 0
    actor._properties = {}
    actor._properties_lock = threading.Lock()
    actor._pipe = None
    calls = []
    actor._open_pipe = lambda _timeout: None
    actor._drop_pipe = lambda: None

    def exchange(_values, *, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise BrokenPipeError("broken")
        return {"request_id": 1, "error": "success"}

    actor._exchange_on_pipe = exchange
    assert actor.exchange(["seek", 3.0], timeout=0.1)["error"] == "success"
    assert len(calls) == 2
    assert actor._reconnect_attempts == 1
    assert actor._degraded is False


def test_mpv_process_crash_marks_actor_degraded_without_retry_loop():
    actor = object.__new__(_MpvCommandActor)
    actor.controller = SimpleNamespace(running=False)
    actor._pipe = None
    actor._read_buffer = b""
    actor._degraded = False
    actor._last_error = ""
    actor._stopping = False
    actor._heartbeat()
    assert actor._degraded is True
    assert actor._last_error == "mpv process exited"
