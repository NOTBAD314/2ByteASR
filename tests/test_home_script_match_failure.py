"""首页「匹配文稿」失败时的提示（2026-10-16 用户反馈：英文匹配点了没反应，按钮又变回开始匹配）。"""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.app import home_script_match as hsm
from twobyteasr.recognition.script_match import ScriptMatchError

WORKER_LOG = ('QWEN3-ASR worker failed (exit 1):\nstdout:\n[2BYTEASR_EVENT] {"phase": "model_loading"}\n'
              'loading Qwen3-ASR\nstderr:\nTraceback (most recent call last):\n  File "qwen_asr_worker.py", line 1\n'
              'RuntimeError: CUDA error: no kernel image is available for execution on the device\n')


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def _raised(exc):
    try:
        raise exc
    except type(exc) as caught:
        return hsm.failure_text(caught)


def test_worker_log_reads_as_its_last_error_line():
    reason, detail = _raised(RuntimeError(WORKER_LOG))
    assert str(reason) == ('QWEN3-ASR 运行失败：'
                           'RuntimeError: CUDA error: no kernel image is available for execution on the device')
    assert WORKER_LOG.strip() in detail and detail.startswith('Traceback')


def test_page_file_too_small_reads_as_advice():
    reason, _ = _raised(RuntimeError('QWEN3-ASR worker failed (exit 1):\nstdout:\n\nstderr:\n'
                                     'OSError: [WinError 1455] 页面文件太小，无法完成操作。'))
    assert '页面文件太小' in str(reason) and '系统管理的大小' in str(reason)


def test_script_errors_and_short_errors_stay_as_written():
    assert _raised(ScriptMatchError('素材里没有可用的音频'))[0] == '素材里没有可用的音频'
    assert _raised(RuntimeError('QWEN3-ASR worker timeout'))[0] == 'QWEN3-ASR worker timeout'
    assert _raised(RuntimeError(''))[0] == 'RuntimeError'


class _Window(QWidget):
    def __init__(self, media):
        super().__init__()
        self.media_paths = [media]
        self.opened = []

    def open_studio_project(self, path, **_kwargs):
        self.opened.append(path)

    def _open_model_workshop(self):
        pass


def test_failed_match_keeps_its_reason_until_an_input_changes(app, monkeypatch, tmp_path):
    media = tmp_path / 'talk.wav'
    media.write_bytes(b'RIFF')
    monkeypatch.setattr(hsm, 'timestamp_model_ready', lambda language='zh': (True, ''))

    def heard(*_args, **_kwargs):
        raise RuntimeError(WORKER_LOG)

    monkeypatch.setattr(hsm, 'heard_tokens', heard)
    window = _Window(str(media))
    seen = {}

    def drive():
        dialog = window._home_script_match_dialog
        dialog._language.setCurrentIndex(dialog._language.findData('en'))
        dialog._script.setPlainText('Hello everyone, welcome back.\nSee you tomorrow.')
        seen['copy_before'] = dialog._copy_error.isVisible()
        dialog._begin()
        dialog._state['job'].wait(10000)
        for _ in range(5):
            app.processEvents()   # the job's failed signal is queued to this thread
        seen['status'] = dialog._status.text()
        seen['start_enabled'] = dialog._start.isEnabled()
        seen['copy_visible'] = dialog._copy_error.isVisible()
        dialog._copy_error.click()
        seen['clipboard'] = QApplication.clipboard().text()
        seen['copied_label'] = dialog._copy_error.text()
        dialog._script.setPlainText('Hello again.')
        seen['status_after_edit'] = dialog._status.text()
        seen['copy_after_edit'] = dialog._copy_error.isVisible()
        dialog.reject()

    QTimer.singleShot(0, drive)
    hsm.open_home_script_match(window)
    window.deleteLater()

    assert seen['copy_before'] is False
    assert seen['status'] == ('匹配没有完成：QWEN3-ASR 运行失败：'
                              'RuntimeError: CUDA error: no kernel image is available for execution on the device')
    assert seen['start_enabled'] and seen['copy_visible']
    assert WORKER_LOG.strip() in seen['clipboard']
    assert seen['copied_label'] == '已复制'
    assert seen['status_after_edit'] == '' and seen['copy_after_edit'] is False
    assert window.opened == []
