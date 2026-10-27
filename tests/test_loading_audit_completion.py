"""A graceful early close is not evidence that the loading matrix completed."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.acceptance import loading_native_probe, studio_loading_audit as module
from twobyteasr.diagnostics import build_identity


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def audit(tmp_path, monkeypatch, app):
    monkeypatch.setenv('TWOBYTEASR_LOADING_RECORD', '0')
    monkeypatch.setenv('TWOBYTEASR_LOADING_FOREGROUND_GATE', '0')
    monkeypatch.setenv('TWOBYTEASR_LOADING_NATIVE_FORENSICS', '1')
    monkeypatch.setattr(build_identity, 'load_build_identity',
                        lambda: SimpleNamespace(to_dict=lambda: {}))
    class Probe:
        def snapshot(self, *_):
            return {'desktop_coverage': {'foreground_owned': True, 'all_points_owned': True}}
    monkeypatch.setattr(loading_native_probe, 'NativeLoadingProbe', Probe)
    window = QWidget()
    window.built_page = lambda _: None
    module.start(window, tmp_path)
    result = window._studio_loading_audit
    result.timer.stop()
    result.native_timer.stop()
    yield result, window, tmp_path
    result.finished = True
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def completed_evidence():
    return dict(matrix_completed_at=20., shutdown_requested_by_audit=True,
                normal_shutdown=True, errors=[],
                checks=[dict(name=name, passed=True) for name in module.MATRIX_CHECK_NAMES],
                sessions=[dict(name=name) for name in module.MATRIX_SESSION_NAMES],
                samples=[dict(active=True, visible=True)])


def test_graceful_close_after_first_check_is_not_matrix_success(audit):
    instance, _, out = audit
    instance.check('cold entry has no Studio', True)
    instance.awaiting_foreground = True
    instance.quit()
    saved = json.loads((out / 'loading.json').read_text('utf8'))
    assert saved['normal_shutdown'] is True
    assert saved['passed'] is False
    assert saved['shutdown_kind'] == 'external_or_early'
    assert saved['capture_visibility_valid'] is False
    assert 'loading matrix did not reach its final close scenario' in saved['completion_errors']
    assert len(saved['checks']) == 1


def test_completed_matrix_is_recognized_during_quit_before_generator_resumes(audit):
    instance, _, out = audit
    instance.native_probe = None
    instance.result.update(completed_evidence())
    instance.result.pop('normal_shutdown')
    instance.closing = True
    instance.quit()
    saved = json.loads((out / 'loading.json').read_text('utf8'))
    assert saved['passed'] is True
    assert saved['shutdown_kind'] == 'completed_matrix'
    assert saved['completion_errors'] == []


def test_recorder_stop_failure_is_seen_before_pass_is_decided(audit, monkeypatch):
    instance, _, out = audit
    instance.native_probe = None
    instance.result.update(completed_evidence(), record_ready_at=1.,
                           recorder_receipts=[dict(role='wgc')])
    monkeypatch.setenv('TWOBYTEASR_LOADING_RECORD', '1')
    def stop_capture():
        instance.result.update(capture_exit_code=1, capture_error='recorder timed out')
    instance.stop_capture = stop_capture
    instance.quit()
    saved = json.loads((out / 'loading.json').read_text('utf8'))
    assert saved['passed'] is False
    assert 'WGC recording did not finish successfully' in saved['completion_errors']


def test_error_finish_followed_by_quit_persists_shutdown_without_changing_failure(audit):
    instance, _, out = audit
    instance.result['errors'].append('controlled failure before matrix completion')
    instance.finish()
    instance.quit()
    saved = json.loads((out / 'loading.json').read_text('utf8'))
    assert saved['normal_shutdown'] is True and saved['passed'] is False
    assert saved['shutdown_kind'] == 'failed_audit'


@pytest.mark.parametrize('removed', ['matrix_completed_at', 'shutdown_requested_by_audit',
                                  'normal_shutdown', 'checks', 'sessions', 'samples'])
def test_final_evidence_rejects_missing_completion_parts(removed):
    data = completed_evidence()
    del data[removed]
    assert module.completion_errors(data)


def test_marker_cannot_make_a_partial_matrix_pass():
    data = completed_evidence()
    data['checks'] = data['checks'][:1]
    assert any('matrix checks' in reason for reason in module.completion_errors(data))


def test_successful_checks_cannot_replace_requested_capture_or_foreground_proof():
    data = completed_evidence()
    errors = module.completion_errors(data, record_required=True, native_required=True,
                                     foreground_required=True)
    assert 'foreground gate was not accepted' in errors
    assert 'requested recording never became ready' in errors
    assert 'WGC recording did not finish successfully' in errors
    assert 'DDA recording did not finish successfully' in errors
    assert 'native recording visibility has no complete valid evidence' in errors


def test_native_visibility_needs_samples_during_recording_and_freezes_commit_receipt(audit):
    instance, window, _ = audit
    receipt = {'status': 'committed', 'batches': [{'applied': True}]}
    window._studio_native_visibility = SimpleNamespace(last_result=receipt)
    instance.native_capture_active = True
    instance.native_sample('before-recorder-ready')
    instance.save_native_samples()
    assert instance.result['capture_visibility_valid'] is False
    instance.result['record_ready_at'] = 1.
    instance.native_sample('recording')
    instance.save_native_samples()
    assert instance.result['capture_visibility_valid'] is True
    assert instance.result['capture_visibility_samples'] == 1
    receipt['batches'][0]['applied'] = False
    assert instance.native_samples[-1]['native_visibility_commit']['batches'][0]['applied'] is True


def test_invalid_native_coverage_is_not_hidden_by_other_valid_samples(audit):
    instance, _, _ = audit
    instance.native_capture_active = True
    instance.result['record_ready_at'] = 1.
    instance.native_sample('valid')
    instance.native_probe.snapshot = lambda *_: {
        'desktop_coverage': {'foreground_owned': False, 'all_points_owned': True}}
    instance.native_sample('lost-foreground')
    instance.save_native_samples()
    assert instance.result['capture_visibility_samples'] == 2
    assert instance.result['capture_visibility_invalid_samples'] == 1
    assert instance.result['capture_visibility_valid'] is False
