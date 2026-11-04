from types import SimpleNamespace

from twobyteasr.app.ui import MainWindow


def test_missing_project_clears_recognition_running_state(monkeypatch, tmp_path):
    failures = []
    page = SimpleNamespace(fail_recognition_runtime=failures.append)
    host = SimpleNamespace(studio_page=page, _ensure_recognition_page=lambda: None)
    monkeypatch.setattr('twobyteasr.app.ui.QMessageBox.warning', lambda *a: None)
    MainWindow._handle_studio_recognition_request(host, 'start_final', str(tmp_path/'missing.mp4'),
                                                  str(tmp_path/'missing.2byteproj'))
    assert failures and '已移动' in failures[0]


def test_save_error_clears_recognition_running_state(monkeypatch, tmp_path):
    media, project = tmp_path/'media.mp4', tmp_path/'project.2byteproj'
    media.write_bytes(b'fixture')
    project.write_text('{}', encoding='utf8')
    failures = []
    def fail_save():
        raise OSError('fixture save failure')
    page = SimpleNamespace(save=fail_save, fail_recognition_runtime=failures.append)
    host = SimpleNamespace(studio_page=page, _ensure_recognition_page=lambda: None)
    monkeypatch.setattr('twobyteasr.app.ui.QMessageBox.critical', lambda *a: None)
    MainWindow._handle_studio_recognition_request(host, 'start_final', str(media), str(project))
    assert failures == ['工程保存失败：fixture save failure']
