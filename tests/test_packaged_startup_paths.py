"""Installed programs must not need write access to the application directory."""
import sys
from pathlib import Path


def test_frozen_startup_log_goes_to_user_data(monkeypatch, tmp_path):
    import quick_start
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path/'read-only-install/2ByteASR.exe'))
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path/'user'))
    target=Path(quick_start._log_path())
    assert target == tmp_path/'user/2ByteASR/logs/2byteasr-startup.log'
    quick_start._append_startup_log('isolated startup test')
    assert target.read_text('utf8').strip() == 'isolated startup test'
    assert not (tmp_path/'read-only-install').exists()


def test_owned_clipboard_is_flushed_before_the_hard_exit(monkeypatch, tmp_path):
    # 2026-10-22: TerminateProcess skips Qt's teardown, which is what hands copied text to Windows.
    import types
    import quick_start
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    flushed = []
    fake = types.SimpleNamespace(windll=types.SimpleNamespace(ole32=types.SimpleNamespace(
        OleFlushClipboard=lambda: flushed.append(1) or 0)))
    monkeypatch.setattr(quick_start, 'ctypes', fake)
    monkeypatch.setattr(quick_start.os, 'name', 'nt')
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path/'user'))
    owns = [False]
    monkeypatch.setattr(type(app.clipboard()), 'ownsClipboard', lambda self: owns[0])
    quick_start._flush_owned_clipboard()
    assert flushed == []  # another program's clipboard is left alone
    owns[0] = True
    quick_start._flush_owned_clipboard()
    assert flushed == [1]


def test_frozen_trace_goes_to_user_data(monkeypatch, tmp_path):
    from twobyteasr.diagnostics import startup_trace
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.delenv('TWOBYTEASR_STARTUP_TRACE', raising=False)
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path/'user'))
    startup_trace._SEEN.discard('RELEASE_PATH_TEST')
    startup_trace.mark('RELEASE_PATH_TEST')
    target=tmp_path/'user/2ByteASR/logs/startup-trace.jsonl'
    assert startup_trace._trace_path() == target
    assert 'RELEASE_PATH_TEST' in target.read_text('utf8')


def test_explicit_trace_destination_is_preserved(monkeypatch, tmp_path):
    from twobyteasr.diagnostics import startup_trace
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('TWOBYTEASR_STARTUP_TRACE', str(tmp_path/'explicit.jsonl'))
    assert startup_trace._trace_path() == tmp_path/'explicit.jsonl'


def test_external_worker_in_installed_bundle_uses_user_log(monkeypatch, tmp_path):
    from twobyteasr.diagnostics import startup_trace
    bundle=tmp_path/'application';bundle.mkdir()
    (bundle/'python310.dll').touch()
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(startup_trace, '__file__', str(bundle/'twobyteasr/diagnostics/startup_trace.py'))
    monkeypatch.delenv('TWOBYTEASR_STARTUP_TRACE', raising=False)
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path/'user'))
    assert startup_trace._trace_path() == tmp_path/'user/2ByteASR/logs/startup-trace.jsonl'
    assert not (bundle/'reports').exists()
