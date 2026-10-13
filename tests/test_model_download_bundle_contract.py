from scripts.verify_model_download_bundle import check_bundle


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, 'utf8')


def test_frozen_gui_does_not_replace_external_worker_source(tmp_path):
    write(tmp_path, 'scripts/download_file_fast.py', 'from twobyteasr.download_diagnostics import redact')
    write(tmp_path, 'scripts/run_repository_download.py', '')
    write(tmp_path, '2ByteASR.exe', 'a frozen GUI may have this module')
    result = check_bundle(tmp_path)
    assert not result['passed']
    assert result['missing'] == ['twobyteasr/download_diagnostics.py']


def test_relative_dependency_of_repository_entry_must_ship(tmp_path):
    write(tmp_path, 'scripts/download_file_fast.py', '')
    write(tmp_path, 'scripts/run_repository_download.py', 'from twobyteasr.repository_download import main')
    write(tmp_path, 'twobyteasr/repository_download.py', 'from .download_diagnostics import redact')
    assert not check_bundle(tmp_path)['passed']
    write(tmp_path, 'twobyteasr/download_diagnostics.py', 'def redact(value): return value')
    assert check_bundle(tmp_path)['passed']


def test_unrelated_lazy_optional_backend_is_outside_startup_gate(tmp_path):
    write(tmp_path, 'scripts/download_file_fast.py', 'def optional():\n from twobyteasr.unshipped_optional import backend')
    write(tmp_path, 'scripts/run_repository_download.py', '')
    assert check_bundle(tmp_path)['passed']
