"""Out of balance pops up at once during recognition (2026-11-18).

User (2026-11-18): users ran out of MOSS / Qwen credits without noticing and only found out when
recognition failed; pop up right away when the balance runs out.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('text, category, service', [
    ('[文件失败] a.mp4：MOSI 账户积分不足（HTTP 402）。请到 MOSI 控制台充值后再试。', '', 'moss'),
    ('cloud asr failed', 'insufficient_credits', 'moss'),
    ('账户欠费或余额不足，服务商拒绝了请求。 Arrearage', '', 'qwen'),
    ('qwen3-asr-flash 的免费额度已用完，且账户开着“仅使用免费额度”。', '', 'qwen'),
    ('本识别任务的AI账号额度不足，已停止新请求；已完成结果保留。', '', 'ai'),
    ('Error code: 402 - Insufficient Balance', '', 'ai'),
    ('request failed', 'quota_exhausted', 'ai'),
])
def test_balance_errors_are_recognised(text, category, service):
    from twobyteasr.app.quota_alert import detect
    problem = detect(text, category)
    assert problem is not None and problem.service == service
    if service in {'moss', 'qwen'}:
        assert problem.link.startswith('https://')
    assert not problem.detail.startswith('[文件失败]')


@pytest.mark.parametrize('text', [
    '[阶段 8/11] 云端模型受限校对', '断句：402 条，中位 5 字', '注册、每天签到都送免费额度',
    'HTTP 401 认证失败', '[队列进度] 已完成 1/3',
])
def test_ordinary_lines_do_not_alarm(text):
    from twobyteasr.app.quota_alert import detect
    assert detect(text) is None


def test_the_qwen_link_follows_the_site_the_user_set_up():
    from twobyteasr.app.quota_alert import qwen_billing_page
    from twobyteasr.providers import dashscope_service as ds
    assert qwen_billing_page('https://maas.qwencloudapi.com/api/v1') == ds.QWEN_CLOUD_BILLING
    assert qwen_billing_page('https://maas.qianwenaiapi.com/api/v1') == ds.QIANWEN_BILLING


def _Window(cancel_button):
    from PySide6.QtWidgets import QWidget

    class Window(QWidget):
        pass
    window = Window()
    window.cancel_run_button = cancel_button
    window.legacy = type('L', (), {'RUNTIME_SETTINGS': {'models': {}}})()
    return window


def _pump(app, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_one_alert_per_run_and_stop_cancels_the_queue(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import quota_alert
    host = QWidget()
    cancel = QPushButton('取消', host)
    host.show()
    stopped = []
    cancel.clicked.connect(lambda: stopped.append(1))
    shown = []
    real = quota_alert.QuotaAlertDialog

    def recording(*args, **kwargs):
        dialog = real(*args, **kwargs)
        shown.append(dialog)
        return dialog
    monkeypatch.setattr(quota_alert, 'QuotaAlertDialog', recording)
    watch = quota_alert.QuotaWatch(_Window(cancel))
    watch.window.legacy.RUNTIME_SETTINGS = {'models': {}}
    assert watch.feed('[阶段 3/11] 云端识别') is None
    assert watch.feed('[文件失败] a.mp4：MOSI 账户积分不足（HTTP 402）。') is not None
    assert watch.feed('[文件失败] b.mp4：MOSI 账户积分不足（HTTP 402）。') is None      # once per run
    _pump(app)
    assert len(shown) == 1 and shown[0].isVisible()
    dialog = shown[0]
    assert dialog.top_up_button is not None and dialog.stop_button is not None
    dialog.stop_button.click()
    _pump(app)
    assert stopped == [1]
    watch.reset()                                                     # a new run may alert again
    assert watch.feed('账户欠费 Arrearage') is not None
    _pump(app)
    assert len(shown) == 2
    shown[1].reject()
    _pump(app)
    host.deleteLater()


def test_without_a_running_queue_there_is_no_stop_and_top_up_opens_the_page(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.app import quota_alert
    opened = []
    monkeypatch.setattr('PySide6.QtGui.QDesktopServices.openUrl', lambda url: opened.append(url.toString()))
    hidden_cancel = QPushButton('取消')                                  # not shown: nothing is running
    watch = quota_alert.QuotaWatch(_Window(hidden_cancel))
    watch.feed('MOSI 账户积分不足（HTTP 402）')
    _pump(app)
    dialog = watch.dialog
    assert dialog is not None and dialog.stop_button is None
    dialog.top_up_button.click()
    _pump(app)
    assert opened == [quota_alert.MOSS_USAGE_PAGE]


def test_the_main_window_feeds_failures_and_log_lines_to_the_watch():
    import inspect
    from twobyteasr.app import ui
    source = inspect.getsource(ui.MainWindow)
    assert 'self._quota_watch().feed(compact)' in source
    assert "self._quota_watch().feed(str(event.error or '')" in source
    assert 'self._quota_watch().reset()' in source
