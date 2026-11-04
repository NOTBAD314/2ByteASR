"""Initial graph binding must not race an acknowledged asynchronous load."""
from collections import deque
from pathlib import Path
from types import MethodType, SimpleNamespace
import threading

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.frame_readiness import video_frame_witness
from twobyteasr.playback.studio_mpv import MpvCommandError, MpvController, _MpvCommandActor
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
from twobyteasr.studio.studio_video_canvas import MpvCanvas
from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin


@pytest.fixture
def initial_binding(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    media = tmp_path / "source.mp4"
    media.write_bytes(b"test media identity; no decoder is started")
    pending = deque()
    commands, errors = [], []
    controller = SimpleNamespace(
        running=True, source_epoch=4, _subtitle_binding_epoch=4,
        _subtitle_media_path="", _seek_apply_lock=threading.Lock(),
        _seek_applied={"generation": 4, "target": 0., "perf_counter": 1.},
    )
    controller._advance_source_epoch = lambda value: setattr(
        controller, "source_epoch", max(value, controller.source_epoch))
    controller.applied_seek_state = MethodType(MpvController.applied_seek_state, controller)
    controller.post_load_at = MethodType(MpvController.post_load_at, controller)
    controller.post_seek = MethodType(MpvController.post_seek, controller)
    controller._post = lambda callback, **kw: pending.append(callback) or True
    controller.set_paused = lambda value: None
    controller.post_set_speed = lambda value: True
    controller.post_clear_media = lambda: True

    def begin_media(path):
        controller._subtitle_binding_epoch += 1
        controller._subtitle_media_path = path
    controller._begin_subtitle_media = begin_media
    state = {"pause": True, "container-fps": 30., "path": str(media),
             "time-pos": 0., "seeking": False, "video-frame-info": None}
    transport = {"file_loaded": False}

    def send(command):
        commands.append(list(command))
        if command[0] == "loadfile":
            transport["file_loaded"] = False
            state["path"] = command[1]
            state["time-pos"] = float(command[-1]["start"])
        if command[0] == "seek" and not transport["file_loaded"]:
            raise MpvCommandError(command, "error running command")
        return {"error": "success"}
    controller._send = send
    actor = _MpvCommandActor.__new__(_MpvCommandActor)
    controller._actor = actor
    actor.controller = controller
    actor._source_generation = 4
    actor._properties_lock = threading.Lock()
    actor._properties = state
    actor._position_observation = {}
    actor._property_sequence = 0
    actor._frame_observation = {"status": "unobserved"}
    actor._frame_witness_request = None
    actor._stopping = False
    actor._seek_target = 0.
    actor.post = lambda callback, **kw: pending.append(callback) or True
    actor.exchange = lambda command, **kw: {"data": state[command[1]]}
    controller.observed_frame = actor.frame_observation
    controller.observed_properties = actor.properties

    def drain():
        while pending:
            try:
                pending.popleft()()
            except BaseException as exc:
                # The real actor stores errors on fire-and-forget requests.
                errors.append(exc)

    canvas = MpvCanvas()
    canvas.controller = controller
    canvas._duration = 12.
    canvas._playback_clock.advance_generation_to(4)
    monkeypatch.setattr(canvas, "_ensure_controller_started", lambda: None)
    monkeypatch.setattr(canvas, "_hold_media_cache", lambda path: None)
    monkeypatch.setattr(canvas, "_defer_media_callback", lambda *a, **kw: None)
    monkeypatch.setattr(canvas, "_release_media_caches_after_idle", lambda: None)
    monkeypatch.setattr(canvas, "remove_compositor_overlay", lambda *a, **kw: None)
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=12000))
    project.validate()
    clip = project.video_tracks[0].clips[0]
    target = dict(key="primary", mode="primary", source_path=str(media),
                  source_ms=0, timeline_in_ms=0, source_in_ms=0,
                  playback_rate=1., track_id="V1", clip_id=clip.id,
                  asset_id=clip.asset_id)
    page = SimpleNamespace(project=project, video=canvas, _active_video_preview_key="",
        _active_video_preview_source_path="", _active_video_preview_clip_id="",
        _preview_path="", _active_video_preview_volume=None,
        _multitrack_preview_layers=lambda ms: [], _multitrack_audio_layers=lambda ms: [],
        _multitrack_preview_target=lambda *a, **kw: dict(target),
        _audio_tail_visual_active=lambda: False, _studio_trace=lambda *a, **kw: None,
        _sync_video_compositor=lambda *a, **kw: None,
        _apply_active_video_track_volume=lambda track: None,
        _maybe_apply_av_sync_map=lambda: None)
    page._activate_multitrack_preview = MethodType(StudioVideoFlowMixin._activate_multitrack_preview, page)
    page.sync = MethodType(StudioVideoFlowMixin._sync_multitrack_preview_at, page)
    page._readiness = SimpleNamespace(generation=12, active=True)
    monkeypatch.setattr(canvas, '_studio_page', lambda: page)
    yield SimpleNamespace(app=app, canvas=canvas, controller=controller, actor=actor,
        media=media, state=state, transport=transport, commands=commands, errors=errors,
        pending=pending, drain=drain, page=page, target=target)
    canvas._timer.stop()
    canvas._sync_timer.stop()
    canvas.controller = None
    canvas.deleteLater()


@pytest.mark.parametrize('load_ack_before_bind', [False, True])
@pytest.mark.parametrize('start_seconds', [0., 1.766])
def test_first_binding_reuses_atomic_load_before_file_loaded(initial_binding, load_ack_before_bind, start_seconds):
    f = initial_binding
    f.canvas._navigation_visible = False  # StackOne prepares the hidden page
    f.target['source_ms'] = round(start_seconds * 1000)
    f.target['source_in_ms'] = round(start_seconds * 1000)
    f.canvas.load(str(f.media), start_seconds=start_seconds)
    if load_ack_before_bind:
        f.drain()  # ACK is optional here; file-loaded is deliberately withheld
        assert f.controller.applied_seek_state()["generation"] == 5
    assert not f.transport["file_loaded"]

    f.page.sync(0)
    f.drain()

    assert [command[0] for command in f.commands] == ["loadfile"], (
        f.commands, f.errors, f.controller.applied_seek_state(), f.actor.frame_observation())
    assert f.canvas._playback_clock.generation == f.controller.source_epoch == 5
    assert not f.errors
    witness_video = SimpleNamespace(controller=f.controller, _media_path=str(f.media),
        _playback_clock=SimpleNamespace(generation=5, exact_seek_pending=False))
    assert not video_frame_witness(witness_video)["ready"]  # ACK is insufficient
    f.transport["file_loaded"] = True
    f.actor._queue_frame_witness()  # real restart, but VO metadata is still absent
    f.drain()
    assert not video_frame_witness(witness_video)["ready"]
    f.state["video-frame-info"] = {"picture-type": "I", "interlaced": False,
        "tff": False, "repeat": False, "estimated-smpte-timecode": "00:00:00;00"}
    f.actor._refresh_frame_witness()
    f.drain()
    assert video_frame_witness(witness_video)["ready"]


def test_restart_before_matching_ack_cannot_certify_load(initial_binding):
    f = initial_binding
    f.canvas.load(str(f.media), start_seconds=0.)
    f.actor.begin_seek(5, 0.)
    f.state['video-frame-info'] = {'picture-type': 'I'}
    f.actor._queue_frame_witness()  # restart arrives before the new load ACK
    assert f.actor._frame_witness_request is None
    f.drain()
    assert f.controller.applied_seek_state()['generation'] == 5
    f.actor._refresh_frame_witness()
    f.drain()
    assert f.actor.frame_observation()['status'] == 'awaiting_restart'
    f.transport['file_loaded'] = True
    f.actor._queue_frame_witness()  # matching restart after ACK is still needed
    f.drain()
    assert f.actor.frame_observation()['status'] == 'ready'


@pytest.mark.parametrize('changed', [
    'requested_source', 'requested_clock', 'clock_generation', 'actor_generation',
    'media_epoch', 'path', 'controller', 'navigation', 'cancel', 'unload', 'cancel_hidden', 'new_open_request',
])
def test_first_load_position_cannot_cross_identity_or_target(initial_binding, changed):
    f = initial_binding
    f.canvas.load(str(f.media), start_seconds=0.)
    f.drain()
    seconds, project_ms, path = 0., 0, str(f.media)
    if changed == 'requested_source':
        seconds = 1.
    elif changed == 'requested_clock':
        f.canvas.set_project_time_mapping(enabled=True)
        project_ms = 1
    elif changed == 'clock_generation':
        f.canvas._playback_clock.begin_seek(0)
    elif changed == 'actor_generation':
        f.controller.source_epoch += 1
    elif changed == 'media_epoch':
        f.controller._subtitle_binding_epoch += 1
    elif changed == 'path':
        path = str(f.media.with_name('different.mp4'))
    elif changed == 'controller':
        f.canvas.controller = SimpleNamespace(running=True, source_epoch=5, _subtitle_binding_epoch=5)
    elif changed == 'navigation':
        f.canvas.set_navigation_visible(False)
    elif changed == 'cancel':
        f.canvas.enter_empty_playback_state()
    elif changed == 'unload':
        f.canvas.unload_project_media()
    elif changed == 'cancel_hidden':
        # StudioReadiness.cancel retires its request even while the already
        # hidden page has not navigated or unloaded media yet.
        f.page._readiness.generation += 1
        f.page._readiness.active = False
    elif changed == 'new_open_request':
        f.page._readiness = SimpleNamespace(generation=12, active=True)
    assert not f.canvas.consume_initial_load_position(path, seconds, project_ms=project_ms)
    assert f.canvas._submitted_load_position is None


def test_load_position_is_consumed_once_and_path_is_normalized(initial_binding):
    f = initial_binding
    f.canvas.load(str(f.media), start_seconds=0.)
    alias = str(f.media.parent / 'unused' / '..' / f.media.name)
    assert f.canvas.consume_initial_load_position(alias, 0., project_ms=0)
    assert not f.canvas.consume_initial_load_position(str(f.media), 0., project_ms=0)


@pytest.mark.parametrize('explicit_seek', [False, True])
def test_changed_or_explicit_seek_still_posts_a_new_position(initial_binding, explicit_seek):
    f = initial_binding
    f.canvas.load(str(f.media), start_seconds=0.)
    f.drain()
    f.transport['file_loaded'] = True
    f.page._explicit_project_seek = explicit_seek
    if not explicit_seek:
        f.target['source_ms'] = 1000
    f.page.sync(1000 if not explicit_seek else 0)
    f.drain()
    assert [command[0] for command in f.commands] == ['loadfile', 'seek']
    assert f.controller.applied_seek_state()['generation'] == 6
    assert f.controller.applied_seek_state()['target'] == (0. if explicit_seek else 1.)
    assert f.canvas._submitted_load_position is None


def test_rejected_load_submission_cannot_be_reused(initial_binding):
    f = initial_binding
    f.controller.post_load_at = lambda *a, **kw: False
    f.controller.load = lambda path: None
    f.canvas.load(str(f.media), start_seconds=0.)
    assert not f.canvas.consume_initial_load_position(str(f.media), 0., project_ms=0)
