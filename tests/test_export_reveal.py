"""Completed exports must use a visible file manager and report failures."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from twobyteasr.system import file_manager
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def output(tmp_path):
    target = tmp_path / '中文 空格 & 路径' / '成片 [完成] #1.mp4'
    target.parent.mkdir()
    target.write_bytes(b'fixture')
    return target


def test_windows_selects_full_output_without_launching_worker(app, output, monkeypatch):
    calls = []
    monkeypatch.setattr(file_manager.sys, 'platform', 'win32')
    monkeypatch.setattr(file_manager, '_windows_reveal', lambda path: calls.append(path) or True)
    monkeypatch.setattr('PySide6.QtGui.QDesktopServices.openUrl', lambda url: pytest.fail('unneeded fallback'))
    assert file_manager.reveal_file(output)
    assert calls == [output.resolve()]


@pytest.mark.parametrize('failure', [False, OSError('shell unavailable')])
def test_shell_failure_opens_parent_folder(app, output, monkeypatch, failure):
    def reveal(path):
        if isinstance(failure, Exception):
            raise failure
        return failure
    urls = []
    monkeypatch.setattr(file_manager.sys, 'platform', 'win32')
    monkeypatch.setattr(file_manager, '_windows_reveal', reveal)
    monkeypatch.setattr('PySide6.QtGui.QDesktopServices.openUrl', lambda url: urls.append(url.toLocalFile()) or True)
    assert file_manager.reveal_file(output)
    assert [Path(path) for path in urls] == [output.parent]


def test_missing_file_does_not_open_shell(app, tmp_path, monkeypatch):
    monkeypatch.setattr(file_manager, '_windows_reveal', lambda path: pytest.fail('missing file'))
    monkeypatch.setattr('PySide6.QtGui.QDesktopServices.openUrl', lambda url: pytest.fail('missing file'))
    assert not file_manager.reveal_file(tmp_path / 'missing.mp4')


def test_non_windows_opens_parent(app, output, monkeypatch):
    urls = []
    monkeypatch.setattr(file_manager.sys, 'platform', 'linux')
    monkeypatch.setattr(file_manager, '_windows_reveal', lambda path: pytest.fail('Windows only'))
    monkeypatch.setattr('PySide6.QtGui.QDesktopServices.openUrl', lambda url: urls.append(url.toLocalFile()) or True)
    assert file_manager.reveal_file(output)
    assert Path(urls[0]) == output.parent


def test_button_reports_failure_then_clears_error_on_success(app, output, monkeypatch):
    page = SimpleNamespace(error=QLabel())
    workspace = SimpleNamespace(_success_output=output, success_page=page)
    monkeypatch.setattr(file_manager, 'reveal_file', lambda path: False)
    StudioExportWorkspace._open_success_folder(workspace)
    assert not page.error.isHidden() and '无法打开资源管理器' in page.error.text()
    monkeypatch.setattr(file_manager, 'reveal_file', lambda path: True)
    StudioExportWorkspace._open_success_folder(workspace)
    assert page.error.isHidden()
    output.unlink()
    StudioExportWorkspace._open_success_folder(workspace)
    assert not page.error.isHidden() and '找不到成片' in page.error.text()
