"""Regressions from report 7ceadb8e: bounded transport and media ownership."""
import threading
import time

import pytest

from twobyteasr.playback.studio_mpv import (
    MpvCommandError, MpvController, MpvIPCTimeoutError, _MpvCommandActor,
)


class Running:
    def poll(self):
        return None


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setattr(_MpvCommandActor, '_heartbeat', lambda self: None)
    exe = tmp_path / 'mpv.exe'
    exe.write_bytes(b'test')
    controller = MpvController(exe)
    controller._process = Running()
    actor = _MpvCommandActor(controller)
    controller._actor = actor
    try:
        yield controller, actor
    finally:
        actor.close()


def test_command_error_is_a_successful_transport_exchange(transport, monkeypatch):
    controller, actor = transport
    actor._last_exchange_ok_ts = time.monotonic() - 20
    monkeypatch.setattr(actor, '_open_pipe', lambda timeout: None)
    def rejected(*args, **kwargs):
        raise MpvCommandError(['get_property', 'time-pos'], 'property unavailable')
    monkeypatch.setattr(actor, '_exchange_on_pipe', rejected)
    with pytest.raises(MpvCommandError):
        actor.call(lambda: actor.exchange(['get_property', 'time-pos']), 1)
    assert controller.source_alive()


def test_outage_has_one_shared_reconnect_budget(transport, monkeypatch):
    _, actor = transport
    opened = []
    def unavailable(timeout):
        opened.append(time.monotonic())
        raise MpvIPCTimeoutError('injected no reply')
    monkeypatch.setattr(actor, '_open_pipe', unavailable)
    for _ in range(6):
        with pytest.raises(RuntimeError):
            actor.call(lambda: actor.exchange(['get_property', 'mpv-version'], timeout=.01), 1)
    assert len(opened) <= 3
    assert actor.status()['recovery_exhausted']


def test_new_load_cannot_expose_previous_media_cache(transport, tmp_path, monkeypatch):
    controller, actor = transport
    actor._properties.update(path='old.mp4', **{'time-pos': 3.3, 'video-out-params': {'w':1080,'h':1920}})
    actor._frame_observation = {'status':'ready', 'media_epoch':0}
    monkeypatch.setattr(actor, 'post', lambda *a, **k: True)
    assert controller.post_load_at(tmp_path/'new.mp4', 0., generation=5)
    assert controller.observed_properties().get('path') is None
    assert controller.observed_frame().get('status') != 'ready'


def test_timed_out_queued_call_is_cancelled(transport):
    _, actor = transport
    occupied, release = threading.Event(), threading.Event()
    def occupy():
        occupied.set()
        release.wait(3)
    actor.post(occupy)
    assert occupied.wait(1)
    side_effect = []
    try:
        with pytest.raises(RuntimeError, match='timed out'):
            actor.call(lambda: side_effect.append('late mutation'), .01)
    finally:
        release.set()
    actor.call(lambda: None, 1)
    assert side_effect == []


def test_late_reply_cannot_be_delivered_as_an_event(transport, monkeypatch):
    controller, actor = transport
    events = []
    replies = iter((b'{"request_id":999,"error":"success","data":"old"}\n',
                    b'{"event":"property-change","name":"pause","data":true}\n',
                    b'{"request_id":1,"error":"success","data":"current"}\n'))
    actor._pipe = type('Pipe', (), {'write':lambda *a: None, 'close':lambda *a: None})()
    monkeypatch.setattr(actor, '_readline_with_timeout', lambda *a, **k: next(replies))
    monkeypatch.setattr(actor, '_handle_event', events.append)
    result = actor.call(lambda: actor._exchange_on_pipe(['get_property', 'mpv-version']), 1)
    assert result['data'] == 'current'
    assert [event['event'] for event in events] == ['property-change']


def test_old_project_commands_and_desired_state_are_revoked(transport, tmp_path, monkeypatch):
    controller, actor = transport
    pending, commands = [], []
    monkeypatch.setattr(actor, 'post', lambda callback, **k: pending.append(callback) or True)
    monkeypatch.setattr(controller, '_send', lambda command: commands.append(command) or {})
    controller.post_set_speed(2.)
    controller._desired_subtitle_path = 'old-project.ass'
    controller.post_load_at(tmp_path/'new.mp4', 0., generation=9)
    pending[0]()
    assert not commands and controller._desired_commands == {}
    assert controller._desired_subtitle_path == ''


def test_failed_restore_releases_every_opened_pipe(transport, monkeypatch):
    from twobyteasr.playback import studio_mpv as mpv
    controller, actor = transport
    closed = []
    class Pipe:
        def close(self):
            closed.append(self)
    monkeypatch.setattr(mpv, 'open_mpv_ipc', lambda *a, **k: Pipe())
    monkeypatch.setattr(actor, '_exchange_on_pipe', lambda *a, **k: {})
    actor._ever_connected = True
    monkeypatch.setattr(controller, '_restore_desired_state',
                        lambda *a, **k: (_ for _ in ()).throw(MpvIPCTimeoutError('restore stalled')))
    for _ in range(6):
        with pytest.raises(RuntimeError):
            actor.call(lambda: actor.exchange(['get_property', 'mpv-version'], timeout=.1), 1)
    assert len(closed) == 3
    assert actor._pipe is None and actor._read_buffer == b''


def test_recovery_diagnostics_preserve_categories_without_native_text(transport, tmp_path):
    import json
    from twobyteasr.diagnostics.event_log import Sanitizer
    controller, _ = transport
    log = tmp_path/'private-project.log'
    log.write_text('hwdec error: PRIVATE_CAPTION_AND_FILENAME\n', encoding='utf8')
    controller._log_path = str(log)
    clean = Sanitizer().clean(controller.recovery_diagnostics())
    encoded = json.dumps(clean)
    assert 'PRIVATE_CAPTION' not in encoded and str(tmp_path) not in encoded
    assert clean['native_tail_categories'] == {'hardware_decode_count':1, 'error_count':1}
    assert clean['actor']['instance_id'] == controller.instance_id
