from pathlib import Path
import sys

from twobyteasr.diagnostics import playback_diagnostic


def test_frozen_manifest_uses_its_own_executable_entry(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Program Files\兔白字幕\2ByteASR.exe')
    assert playback_diagnostic.runner_command(Path('scripts/verify_playback_cadence.py')) == [
        sys.executable, '--playback-diagnostic']


def test_diagnostic_output_root_survives_coordinator_temp_redirection(monkeypatch, tmp_path):
    root = tmp_path / '2ByteASR-playback-diagnostics' / 'tmp'
    monkeypatch.setenv('TWOBYTEASR_DIAGNOSTIC_OUTPUT_ROOT', str(root))
    monkeypatch.setattr(playback_diagnostic.tempfile, 'tempdir', str(root/'coordinator'/'temp'))
    assert playback_diagnostic.output_root() == root.resolve()


def test_help_loads_packaged_runner_without_creating_profiles(monkeypatch, capsys):
    calls = []
    from twobyteasr import test_isolation
    monkeypatch.setattr(test_isolation, 'install', lambda: calls.append(True))
    import pytest
    with pytest.raises(SystemExit) as error:
        playback_diagnostic.main(['--help'])
    assert error.value.code == 0
    assert not calls
    assert '--generate-media' in capsys.readouterr().out
