"""Command-local wait evidence without changing pipe retries or completions."""
from collections import deque
import json
import threading
from types import SimpleNamespace

import pytest

from twobyteasr.playback import studio_mpv as mpv


def actor_fixture(monkeypatch):
    actor = object.__new__(mpv._MpvCommandActor)
    actor._init_request_metrics()
    actor.controller = SimpleNamespace(_request_id=0, running=True)
    actor._condition = threading.Condition()
    actor._requests = deque()
    actor._stopping = False
    actor._reconnect_attempts = 0
    actor._command_error_count = 0
    actor._thread = threading.current_thread()
    actor._handle_event = lambda event: None
    actor._remember_property = lambda *args, **kwargs: None
    actor._drop_pipe = lambda: None
    actor._open_pipe = lambda timeout: None
    actor._pipe = SimpleNamespace(write=lambda data: None)
    clock = iter(n*.002 for n in range(10000))
    monkeypatch.setattr(mpv.time, 'perf_counter', lambda: next(clock))
    monkeypatch.setattr(mpv.time, 'sleep', lambda requested: None)
    def response(timeout, **kwargs):
        actor._sleep_for_response(.001)
        return json.dumps(dict(request_id=actor.controller._request_id, error='success')).encode()
    actor._readline_with_timeout = response
    return actor


def test_each_request_has_independent_receipt_and_real_zero_is_distinct(monkeypatch):
    actor = actor_fixture(monkeypatch)
    first = actor.exchange(['overlay-add', 0])['_ipc_poll_receipt']
    second = actor.exchange(['get_property', 'time-pos'])['_ipc_poll_receipt']
    assert first['calls'] == second['calls'] == 1
    assert first['wall_ms'] == pytest.approx(2)
    assert first['requested_ms'] == 1
    assert first['attempts'][0]['request_id'] == 1
    assert second['attempts'][0]['request_id'] == 2
    first['attempts'][0]['calls'] = 99
    assert second['attempts'][0]['calls'] == 1
    actor._readline_with_timeout = lambda timeout, **kwargs: json.dumps(
        dict(request_id=actor.controller._request_id, error='success')).encode()
    zero = actor.exchange(['get_property', 'pause'])['_ipc_poll_receipt']
    assert zero['status'] == 'measured' and zero['calls'] == 0 and zero['wall_ms'] == 0
    assert actor._poll_summary([])['wall_ms'] is None
    assert actor._active_poll_receipt is None and actor._poll_attempt_sink is None


def test_retry_retains_both_attempts_but_excludes_reconnect_replay(monkeypatch):
    actor = actor_fixture(monkeypatch)
    original = actor._readline_with_timeout
    opened = []
    def open_pipe(timeout):
        opened.append(True)
        if len(opened) == 2:
            actor._exchange_on_pipe(['set_property', 'volume', 100])
    actor._open_pipe = open_pipe
    def response(timeout, **kwargs):
        if actor.controller._request_id == 1:
            actor._sleep_for_response(.001)
            raise mpv.MpvIPCTimeoutError('first response timed out')
        return original(timeout)
    actor._readline_with_timeout = response
    receipt = actor.exchange(['overlay-add', 0])['_ipc_poll_receipt']
    assert [r['request_id'] for r in receipt['attempts']] == [1, 3]
    assert [r['status'] for r in receipt['attempts']] == ['failed', 'acknowledged']
    assert receipt['calls'] == 2 and actor._ipc_sleep_count == 3
    assert actor._reconnect_attempts == 1


def test_nested_event_exchange_has_separate_wait_ownership(monkeypatch):
    actor = actor_fixture(monkeypatch)
    responses = iter(({'event':'test'}, {'request_id':2,'error':'success'},
                      {'request_id':1,'error':'success'}))
    nested = []
    def response(_, **kwargs):
        actor._sleep_for_response(.001)
        return json.dumps(next(responses)).encode()
    actor._readline_with_timeout = response
    actor._handle_event = lambda event: nested.append(actor.exchange(['get_property','time-pos']))
    outer = actor.exchange(['overlay-add',0])['_ipc_poll_receipt']
    inner = nested[0]['_ipc_poll_receipt']
    assert outer['calls'] == 2 and inner['calls'] == 1
    assert [r['request_id'] for r in outer['attempts']] == [1]
    assert [r['request_id'] for r in inner['attempts']] == [2]


def test_stopping_exchange_keeps_failure_receipt_without_retry(monkeypatch):
    actor = actor_fixture(monkeypatch)
    actor._stopping = True
    def response(_, **kwargs):
        actor._sleep_for_response(.001)
        raise RuntimeError('mpv actor is stopping')
    actor._readline_with_timeout = response
    with pytest.raises(RuntimeError) as failure:
        actor.exchange(['overlay-add',0])
    assert failure.value._ipc_poll_receipt['calls'] == 1
    assert actor._reconnect_attempts == 0
    assert actor._active_poll_receipt is None


def test_timeout_and_command_error_do_not_leave_wait_ownership(monkeypatch):
    actor = actor_fixture(monkeypatch)
    def timeout(_, **kwargs):
        actor._sleep_for_response(.001)
        raise mpv.MpvIPCTimeoutError('no reply')
    actor._readline_with_timeout = timeout
    with pytest.raises(mpv.MpvIPCTimeoutError) as error:
        actor.exchange(['overlay-add', 0])
    assert error.value._ipc_poll_receipt['calls'] == 2
    assert actor._active_poll_receipt is None and actor._poll_attempt_sink is None
    actor._readline_with_timeout = lambda _, **kwargs: json.dumps(
        dict(request_id=actor.controller._request_id, error='invalid parameter')).encode()
    with pytest.raises(mpv.MpvCommandError) as rejected:
        actor.exchange(['overlay-add', 0])
    assert len(rejected.value._ipc_poll_receipt['attempts']) == 1
    assert rejected.value._ipc_poll_receipt['calls'] == 0
    assert actor._reconnect_attempts == 1


def test_compact_and_normal_snapshots_do_not_expand_raw_history(monkeypatch):
    from twobyteasr.diagnostics import playback_probe
    actor = actor_fixture(monkeypatch)
    for _ in range(2000):
        actor._sleep_for_response(.001)
    monkeypatch.setattr(playback_probe, 'ENABLED', True)
    monkeypatch.setattr(playback_probe, 'LIGHT', True)
    assert len(actor._ipc_sleep_samples) == 1200
    for raw in (False, True):
        result = actor.request_metrics(include_raw=raw)
        assert result['ipc_response_poll_sleep_samples'] is None
        assert result['ipc_response_poll_sleep_calls'] == 2000
    monkeypatch.setattr(playback_probe, 'LIGHT', False)
    assert actor.request_metrics()['ipc_response_poll_sleep_samples'] is None
    detailed = actor.request_metrics(include_raw=True)
    assert len(detailed['ipc_response_poll_sleep_samples']) == 1200
    detailed['ipc_response_poll_sleep_samples'][0]['wall_ms'] = 999
    assert actor.request_metrics(include_raw=True)['ipc_response_poll_sleep_samples'][0]['wall_ms'] != 999


@pytest.mark.parametrize('mode', ['applied', 'invalid', 'discarded', 'failed'])
def test_optional_metrics_callback_keeps_existing_completion_contract(mode):
    controller = object.__new__(mpv.MpvController)
    events = []
    receipt = dict(status='measured', calls=2, attempts=[dict(request_id=7)])
    def send(_):
        if mode == 'failed':
            error = mpv.MpvIPCTimeoutError('timeout')
            error._ipc_poll_receipt = receipt
            raise error
        return {'_ipc_poll_receipt': receipt}
    controller._send = send
    controller._record_visual_applied = lambda *args: None
    def post(callback, **kwargs):
        if mode == 'discarded':
            kwargs['on_discard']()
            return False
        callback()
        return True
    controller._post = post
    def run():
        return controller.post_raw_overlay(0, 'test.rgba', x=0, y=0, width=2, height=2, stride=8,
            valid_when=lambda: mode != 'invalid', on_metrics=lambda value: events.append(('metrics', value)),
            on_applied=lambda value: events.append(('applied', value)))
    if mode == 'failed':
        with pytest.raises(mpv.MpvIPCTimeoutError): run()
    else: run()
    assert events[-1] == ('applied', mode == 'applied')
    assert events[0] == ('metrics', None if mode in ('invalid','discarded') else receipt)


def test_metrics_consumer_failure_still_releases_publisher_ack_wait():
    controller = object.__new__(mpv.MpvController)
    completed = []
    controller._send = lambda command: {}
    controller._record_visual_applied = lambda *args: None
    controller._post = lambda callback, **kwargs: callback()
    def broken(_): raise RuntimeError('diagnostic consumer failed')
    with pytest.raises(RuntimeError, match='diagnostic consumer'):
        controller.post_raw_overlay(0, 'test.rgba', x=0, y=0, width=2, height=2, stride=8,
            on_metrics=broken, on_applied=completed.append)
    assert completed == [True]


def test_default_keeps_sleep_and_does_not_create_timer(monkeypatch):
    from twobyteasr.playback import windows_poll_timer
    monkeypatch.delenv('TWOBYTEASR_MPV_POLL_WAIT',raising=False)
    actor=actor_fixture(monkeypatch)
    def forbidden():raise AssertionError('default must not create experimental timer')
    monkeypatch.setattr(windows_poll_timer,'HighResolutionPollTimer',forbidden)
    receipt=actor.exchange(['overlay-add',0])['_ipc_poll_receipt']
    assert receipt['calls']==1 and receipt['timer_poll_calls']==0


@pytest.mark.skipif(mpv.os.name!='nt',reason='Windows-only poll experiment')
def test_timer_poll_is_separately_attributed_and_not_called_readiness(monkeypatch):
    from twobyteasr.playback import windows_poll_timer
    monkeypatch.setenv('TWOBYTEASR_MPV_POLL_WAIT','highres_timer')
    actor=actor_fixture(monkeypatch)
    requested=[]
    wait=SimpleNamespace(wait=lambda value:requested.append(value) or 'timer_signalled',close=lambda:None)
    monkeypatch.setattr(windows_poll_timer,'HighResolutionPollTimer',lambda:wait)
    receipt=actor.exchange(['overlay-add',0])['_ipc_poll_receipt']
    assert requested==[.001]
    assert receipt['calls']==0 and receipt['wall_ms']==0
    assert receipt['timer_poll_calls']==1 and receipt['timer_poll_wall_ms']==pytest.approx(2)
    assert receipt['attempts'][0]['timer_poll_last_outcome']=='timer_signalled'
    snapshot=actor.request_metrics()
    assert snapshot['poll_wait_last_observed']=='highres_timer_poll'
    assert snapshot['ipc_read_transport']=='windows-peek-sync'
    assert snapshot['ipc_response_poll_sleep_calls']==0
    assert snapshot['ipc_timer_poll_calls']==1
    assert snapshot['ipc_timer_poll_samples'] is None


@pytest.mark.skipif(mpv.os.name!='nt',reason='Windows-only poll experiment')
def test_unsupported_timer_explicitly_reports_sleep_fallback(monkeypatch):
    from twobyteasr.playback import windows_poll_timer
    monkeypatch.setenv('TWOBYTEASR_MPV_POLL_WAIT','highres_timer')
    actor=actor_fixture(monkeypatch)
    def unsupported():raise OSError('unsupported timer flag')
    monkeypatch.setattr(windows_poll_timer,'HighResolutionPollTimer',unsupported)
    receipt=actor.exchange(['overlay-add',0])['_ipc_poll_receipt']
    snapshot=actor.request_metrics()
    assert receipt['calls']==1 and receipt['timer_poll_calls']==0
    assert snapshot['poll_wait_last_observed']=='time_sleep'
    assert 'unsupported timer flag' in snapshot['poll_timer_error']


def test_unsolicited_event_lines_do_not_renew_the_response_deadline(monkeypatch):
    actor=actor_fixture(monkeypatch)
    clock=[0.];deadlines=[];events=[]
    monkeypatch.setattr(mpv.time,'monotonic',lambda:clock[0])
    def event_line(timeout,*,deadline):
        deadlines.append(deadline);clock[0]+=.006
        return b'{"event":"unsolicited"}\n'
    actor._readline_with_timeout=event_line
    actor._handle_event=events.append
    with pytest.raises(mpv.MpvIPCTimeoutError):
        actor._exchange_on_pipe(['overlay-add',0],timeout=.01)
    assert deadlines==[.01,.01]
    assert len(events)==1
