"""Opening a project fails only when nothing moves (2026-10-21).

User report: opening often stopped at 「建立时间轴失败 / 准备超时」. The 30 s limit ran
from the click, so the autosave recovery prompt left open for a while, or a large
project still loading, failed although nothing was stuck.
"""
import threading
import time
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from twobyteasr.caption_style.style_cleanup import prune_unused_derived_payload
from twobyteasr.projects.studio_project_controller import StudioProjectController
from twobyteasr.studio.studio_readiness import StudioReadiness, caption_rows_prepared

APP = QApplication.instance() or QApplication([])


def _gate(*, last_progress_age, completed=(), reader=None):
    now = time.perf_counter()
    failures = []
    gate = SimpleNamespace(
        active=True, generation=1, _owns_request=lambda *a, **k: True,
        page=SimpleNamespace(video=SimpleNamespace(controller=None)),
        completed=set(completed), started=now - 500, last_tick=now,
        last_progress=now - last_progress_age, _reader=reader,
        profile={'gui_gaps_ms': []}, steps=None, hydrated=False,
        TASKS=StudioReadiness.TASKS,
        _player_start_failure=lambda: '', _failed_stage=lambda: '建立时间轴',
        fail=lambda stage, error: failures.append((stage, error)))
    return gate, failures


def test_a_long_open_that_keeps_moving_is_not_a_timeout():
    # Started 500 s ago (the old rule failed at 30 s); the last step moved 5 s ago.
    gate, failures = _gate(last_progress_age=5)
    StudioReadiness._tick(gate)
    assert failures == []


def test_thirty_seconds_without_progress_still_fails():
    gate, failures = _gate(last_progress_age=31)
    StudioReadiness._tick(gate)
    assert failures == [('建立时间轴', '准备超时；请检查素材和播放器状态。')]
    assert gate.profile['stalled_s'] >= 31


def test_a_live_reader_gets_longer_but_not_forever():
    release = threading.Event()
    reader = threading.Thread(target=release.wait, daemon=True)
    reader.start()
    try:
        gate, failures = _gate(last_progress_age=60, reader=reader)
        StudioReadiness._tick(gate)
        assert failures == []
        gate, failures = _gate(last_progress_age=121, reader=reader)
        StudioReadiness._tick(gate)
        assert len(failures) == 1
        # Once 读取工程 is done the reader no longer extends the limit.
        gate, failures = _gate(last_progress_age=60, reader=reader, completed={'读取工程'})
        StudioReadiness._tick(gate)
        assert len(failures) == 1
    finally:
        release.set()


def test_captions_prepared_one_by_one_count_as_progress():
    state = dict(expected_cue_ids=['a', 'b'], cue_pixels=[dict(cue_id='a', status='rendered'),
                                                         dict(cue_id='b', status='pending')])
    assert caption_rows_prepared(state) == 1
    scene = SimpleNamespace(active=True, trace=lambda: state)
    page = SimpleNamespace(project=SimpleNamespace(media=SimpleNamespace(path=''), cues=[object()]),
                           video=SimpleNamespace(_paused=True, controller=None), _caption_scene=scene,
                           _preview_path='ready.ass', audio_engine=SimpleNamespace(telemetry_snapshot=lambda: {}),
                           _playback_buffers_ready=lambda: True,
                           _present_caption_scene=lambda: None, _studio_trace=lambda *a, **k: None)
    gate, failures = _gate(last_progress_age=20, completed={'读取工程', '建立时间轴', '准备播放器', '准备音频'})
    gate.page, gate.hydrated, gate.painted, gate.generation = page, True, False, 1
    gate.mark = gate.completed.add
    gate._set_stage_label = lambda _stage: None
    before = gate.last_progress
    StudioReadiness._tick(gate)
    assert failures == [] and gate.last_progress > before and gate._caption_rows_prepared == 1


def test_recovery_prompt_time_is_not_counted(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox, QWidget
    gate = SimpleNamespace(last_progress=time.perf_counter(), profile={})
    page = QWidget()
    page._readiness = SimpleNamespace(user_wait=lambda: StudioReadiness.user_wait(gate))
    controller = object.__new__(StudioProjectController)
    controller.page = page
    monkeypatch.setattr(QMessageBox, "exec", lambda self: time.sleep(0.2) or 0)
    before = gate.last_progress
    assert controller._recovery_choice(tmp_path / "missing.2byteproj") == "saved"
    assert gate.last_progress - before >= 0.19
    assert gate.profile['user_wait_ms'] >= 190
    page.deleteLater()


def test_raw_project_data_loses_only_unreferenced_derived_styles():
    payload = dict(
        styles=[dict(id='default'), dict(id='brand'), dict(id='brand-cue-aaaa1111'),
                dict(id='brand-cue-bbbb2222'), dict(id='brand-scope-cccc3333')],
        style_recipes={'default': {}, 'brand-cue-aaaa1111': {}, 'brand-cue-bbbb2222': {},
                       'brand-scope-cccc3333': {}},
        cues=[dict(id='c1', style_id='brand-cue-bbbb2222'), dict(id='c2')],
        speakers=[dict(id='S1', style_id=' brand-scope-cccc3333 ')],
    )
    assert prune_unused_derived_payload(payload) == {'brand-cue-aaaa1111'}
    assert [style['id'] for style in payload['styles']] == ['default', 'brand', 'brand-cue-bbbb2222',
                                                          'brand-scope-cccc3333']
    assert set(payload['style_recipes']) == {'default', 'brand-cue-bbbb2222', 'brand-scope-cccc3333'}
    # Nothing to drop leaves the data untouched.
    assert prune_unused_derived_payload(payload) == set()
