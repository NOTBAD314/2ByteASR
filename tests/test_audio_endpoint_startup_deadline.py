from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.playback import audio_process


@pytest.fixture
def bridge(tmp_path):
    app = QApplication.instance() or QApplication([])
    worker = audio_process.AudioProcessBridge(tmp_path / 'ffmpeg.exe')
    worker.process = SimpleNamespace(pid=42, poll=lambda: None)
    worker._sent_at = 100.
    worker._ack_pending = True
    yield worker
    worker.process = None
    worker.deleteLater()
    app.processEvents()


def test_slow_first_device_enumeration_keeps_the_same_endpoint(bridge, monkeypatch):
    monkeypatch.setattr(audio_process.time, 'monotonic', lambda: 105.5)
    observations = []
    bridge.telemetry.connect(observations.append)
    bridge._check_health()
    assert bridge._ack_pending and not bridge._broken
    assert observations == []
    assert bridge._recovery.attempts == 0


def test_first_sync_still_has_a_finite_deadline(bridge, monkeypatch):
    monkeypatch.setattr(audio_process.time, 'monotonic', lambda: 110.1)
    observations = []
    bridge.telemetry.connect(observations.append)
    bridge._check_health()
    bridge._check_health()
    assert bridge._broken and not bridge._ack_pending
    assert [state['state'] for state in observations] == ['ENDPOINT_FAILED']


def test_normal_controls_keep_the_short_deadline(bridge, monkeypatch):
    bridge._sync_timeout = 3.
    monkeypatch.setattr(audio_process.time, 'monotonic', lambda: 103.1)
    bridge._check_health()
    assert bridge._broken and not bridge._ack_pending


@pytest.mark.parametrize('failure', ['exit', 'disconnected'])
def test_actual_endpoint_failures_do_not_wait_for_cold_deadline(bridge, monkeypatch, failure):
    monkeypatch.setattr(audio_process.time, 'monotonic', lambda: 100.1)
    if failure == 'exit':
        bridge.process.poll = lambda: 1
    else:
        bridge._broken = True
    bridge._check_health()
    assert bridge._failure_emitted and not bridge._ack_pending
