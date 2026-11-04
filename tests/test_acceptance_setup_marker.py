from pathlib import Path

import quick_start


def test_isolated_source_acceptance_never_refreshes_shared_setup_marker(tmp_path, monkeypatch):
    marker = tmp_path/'2byteasr.setup-complete'
    marker.write_text('operator timestamp', encoding='ascii')
    runtime = tmp_path/'.venv-main/Scripts/python.exe'
    runtime.parent.mkdir(parents=True); runtime.write_bytes(b'fixture')
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path/'tmp/qa'))
    monkeypatch.setattr(quick_start, 'application_root', lambda:str(tmp_path))
    quick_start._write_setup_marker()
    assert marker.read_text('ascii') == 'operator timestamp'


def test_normal_developer_start_keeps_existing_setup_self_heal(tmp_path, monkeypatch):
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT', raising=False)
    runtime = tmp_path/'.venv-main/Scripts/python.exe'
    runtime.parent.mkdir(parents=True); runtime.write_bytes(b'fixture')
    monkeypatch.setattr(quick_start, 'application_root', lambda:str(tmp_path))
    quick_start._write_setup_marker()
    assert (tmp_path/'2byteasr.setup-complete').is_file()
