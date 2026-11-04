"""P1-4 回归测试：UI 开始任务重入守卫（最多一个 active pipeline run）。

安全不变量：任意时刻 MainWindow 最多只有一个 active run——preparing /
runtime checking / worker starting / worker running / cancelling 任一
状态下，新的 _start_run 必须被拒绝（no-op：不创建新 token、不覆盖
worker、不重置 UI）。重复调用被拒绝后，原 worker/token identity 不变。
完成/失败/取消/启动前异常后状态必须释放，可再次开始。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.recognition.service import CancellationToken, MediaResult, QueueResult
from twobyteasr.app.ui import MainWindow, PipelineWorker

app = QApplication.instance() or QApplication([])


class _FakeCombo:
    def __init__(self, data="moss", text="测试游戏"):
        self._data = data
        self._text = text

    def currentData(self):
        return self._data

    def currentText(self):
        return self._text

    def text(self):
        return self._text


class _FakeButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)

    def isEnabled(self):
        return self.enabled

    def isChecked(self):
        return False

    def __getattr__(self, name):
        # UI 骨架兜底：clear/setValue/setText/setCurrentIndex/set_active 等
        # 全部为 no-op，测试只关注 guard 语义。
        return lambda *args, **kwargs: None


class _FakeTimer:
    def start(self):
        pass

    def stop(self):
        pass


class _FakeLegacy:
    RUNTIME_SETTINGS = {
        "models": {
            "qwen_asr_model": "Qwen/Qwen3-ASR-1.7B",
            "polish_model": "qwen3.7-flash-2026-07-15",
            "group_model": "qwen3.7-flash-2026-07-15",
        }
    }

    def canonicalize_runtime_game_name(self, name):
        return name or ""

    def save_runtime_game_history(self, name):
        pass


class _FakePipeline:
    def set_cancellation_token(self, token):
        pass

    def check_runtime(self, legacy):
        pass

    def precompute_moss_batch_cache(self, paths, legacy):
        pass

    def process_media(self, media_path, index, total, legacy, **kwargs):
        return f"{media_path}.txt", f"{media_path}.srt", 1.0


@pytest.fixture
def window(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    win._run_in_progress = False
    win.media_paths = ["dummy.mp4"]
    win.primary_asr_backend = _FakeCombo(data="moss")
    win.qwen_asr_backend = _FakeCombo(data="local")
    win.qwen_asr_api_provider = _FakeCombo(data="dashscope")
    win.qwen_asr_api_model = _FakeCombo(text="qwen3-asr-flash")
    win.qwen_asr_api_url = _FakeCombo(text="https://dashscope.invalid/v1")
    win.firered_asr_backend = _FakeCombo(data="local")
    win.game_box = _FakeCombo()
    win.terms = _FakeButton()
    win.review_track = _FakeButton()
    win.jianying_txt = _FakeButton()
    win.speaker_tracks = _FakeButton()
    win.refresh_polish = _FakeButton()
    win.refresh_group = _FakeButton()
    win.expected_speakers = _FakeCombo(data="0")
    win.overwrite = _FakeCombo(data="overwrite")
    win.legacy = _FakeLegacy()
    win.pipeline = _FakePipeline()
    win.startup_self_test = None
    win.start_button = _FakeButton()
    win.cancel_run_button = _FakeButton()
    win.progress_bar = _FakeButton()  # 只需 setValue
    win.progress_percent = _FakeButton()  # 只需 setText
    win.progress_stage = _FakeButton()
    win.progress_resource = _FakeButton()
    win._progress_timer = _FakeTimer()
    win.workflow = _FakeButton()
    win.pages = _FakeButton()
    win._active_stages = set()
    win._completed_stages = set()
    win._failed_stages = set()
    win.event_log = _FakeButton()
    win.console_log = _FakeButton()
    win.started_at = 0.0
    win._last_failed_items = []
    win.worker = None
    win.token = None
    win.retry_failed_button = _FakeButton()
    win.result_exit_code = 0
    win.media_frame = _FakeButton()
    win.result_icon = _FakeButton()
    win.result_title = _FakeButton()
    win.result_summary = _FakeButton()
    win.result_files = _FakeButton()
    win.result_console = _FakeButton()

    # 记录型 stub：验证调用次数与顺序
    calls = {"ensure_cuda": 0, "worker_start": 0, "handle_result": 0}
    win._calls = calls
    monkeypatch.setattr(win, "_save_asr_configuration", lambda **kw: True)
    monkeypatch.setattr(win, "_save_ai_configuration", lambda **kw: True)
    monkeypatch.setattr(win, "_append_feed", lambda *a, **k: None)
    monkeypatch.setattr(win, "_handle_event", lambda *a, **k: None)
    monkeypatch.setattr(win, "_append_console_line", lambda *a, **k: None)
    monkeypatch.setattr(win, "_refresh_media_summary", lambda: None)

    def fake_ensure_cuda():
        calls["ensure_cuda"] += 1
        return True

    monkeypatch.setattr(win, "_ensure_cuda_runtime", fake_ensure_cuda)
    monkeypatch.setattr(win, "_ensure_runtime_environment", lambda: True)
    monkeypatch.setattr(win, "_show_task_notification", lambda *a, **k: None)
    monkeypatch.setattr(win, "_refresh_progress_cards", lambda: None)
    monkeypatch.setattr(
        "twobyteasr.app.ui.missing_selected_local_models", lambda values: []
    )
    # 骨架未调用 QWidget.__init__，UI 语言刷新（findChildren）不在 guard 测试范围
    monkeypatch.setattr("twobyteasr.app.ui.apply_ui_language", lambda *a, **k: None)
    # This fixture intentionally has no native QWidget. Keep deferred timing
    # without passing that incomplete skeleton as a QObject timer context.
    from twobyteasr.app.ui import QTimer
    single_shot=QTimer.singleShot
    monkeypatch.setattr(QTimer,'singleShot',lambda delay,*callbacks:single_shot(delay,lambda:callbacks[-1]()))

    real_start = PipelineWorker.start

    def counting_start(self):
        calls["worker_start"] += 1
        # 真实启动会跑 fake pipeline；测试聚焦 guard，不启动线程
        return None

    monkeypatch.setattr(PipelineWorker, "start", counting_start)
    return win


def _started_worker(window):
    """执行一次完整 _start_run，返回 (worker, token)。"""
    window._start_run()
    return window.worker, window.token


def _release_after_result(window):
    window._handle_result(
        QueueResult((MediaResult("dummy.mp4", "success"),), 1.0)
    )


def test_degraded_completion_keeps_studio_handoff(window, monkeypatch, tmp_path):
    import json
    target = tmp_path / 'recovered.2byteproj'
    target.write_text('{}')
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'status': 'degraded_success', 'result': {'cue_count': 1127},
        'polishing_summary': {'success_batches': 54, 'success_cues': 858, 'fallback_cues': 0},
        'review_severity_counts': {'warning': 3, 'review': 68}}))
    window._studio_recognition_context = {'media_path': 'dummy.mp4', 'project_path': str(target)}
    calls = []
    monkeypatch.setattr(window, '_finish_studio_recognition', calls.append)
    window._handle_result(QueueResult((MediaResult('dummy.mp4', 'degraded_success',
        project_path=str(target), report_json_path=str(report)),), 637.847))
    app.processEvents()
    assert calls == [str(target)]
    assert not window._run_in_progress


def test_case_a_second_start_during_preparation_is_rejected(window, monkeypatch):
    """Case A：第一次进入配置准备阶段，第二次立即调用 → 拒绝。"""
    enter = threading.Event()
    release = threading.Event()
    save_calls = 0

    def blocking_save_asr(**_kwargs):
        nonlocal save_calls
        save_calls += 1
        enter.set()
        release.wait(5)
        return True

    monkeypatch.setattr(window, "_save_asr_configuration", blocking_save_asr)
    monkeypatch.setattr(PipelineWorker, "start", lambda self: None)

    results = {}

    def first_start():
        results["first"] = window._start_run()

    thread = threading.Thread(target=first_start)
    thread.start()
    assert enter.wait(5), "第一次调用应进入配置准备"

    # 第二次调用发生在第一次仍处于准备阶段时
    results["second"] = window._start_run()
    assert save_calls == 1, "第二次调用不得进入准备流程"
    assert results["second"] is None

    release.set()
    thread.join(5)


def test_case_b_second_start_while_worker_running_is_rejected(window):
    """Case B：worker 运行中再次 _start_run → 不创建第二 worker、不建新 token。"""
    worker1, token1 = _started_worker(window)
    assert window._run_in_progress is True

    window._start_run()
    assert window.worker is worker1, "不得覆盖 worker identity"
    assert window.token is token1, "不得覆盖 token identity"
    assert window._calls["worker_start"] == 1, "不得启动第二个 worker"


def test_case_c_second_start_during_cuda_check_is_rejected(window, monkeypatch):
    """Case C：配置准备阻塞窗口内重复调用 → 第二次拒绝。"""
    # 与 Case A 相同窗口；这里断言第二次调用时 worker/token 均未创建。
    enter = threading.Event()
    release = threading.Event()

    def blocking_save_asr(**_kwargs):
        enter.set()
        release.wait(5)
        return True

    monkeypatch.setattr(window, "_save_asr_configuration", blocking_save_asr)
    monkeypatch.setattr(PipelineWorker, "start", lambda self: None)
    results = {}
    thread = threading.Thread(target=lambda: results.setdefault("first", window._start_run()))
    thread.start()
    assert enter.wait(5)
    window._start_run()
    assert window.worker is None, "被拒绝的重复调用不得创建 worker"
    assert window.token is None, "被拒绝的重复调用不得创建 token"
    release.set()
    thread.join(5)


def test_case_d_retry_and_manual_start_share_one_guard(window):
    """Case D：_retry_failed_items 的 singleShot 与手动开始竞争 → 只有一个 run。"""
    window._last_failed_items = [MediaResult("dummy.mp4", "failed", error="x")]
    window.media_paths = ["a.mp4"]
    window._retry_failed_items()  # 排队 singleShot(0, _start_run)
    window._start_run()  # 手动立即开始（先占用）
    app.processEvents()  # 处理 singleShot → 应被 guard 拒绝
    assert window._calls["worker_start"] == 1, "retry 与手动开始最终只能有一个 run"


def test_case_e_rejected_duplicate_keeps_worker_and_token_identity(window):
    """Case E：重复调用被拒绝时 worker/token identity 保持不变。"""
    worker1, token1 = _started_worker(window)
    window._start_run()
    window._start_run()
    assert window.worker is worker1
    assert window.token is token1


def test_case_f_after_normal_completion_can_start_again(window):
    """Case F：正常完成后状态释放，可再次开始。"""
    _started_worker(window)
    assert window._run_in_progress is True
    _release_after_result(window)
    assert window._run_in_progress is False
    assert window.start_button.isEnabled() is True
    worker2, _ = _started_worker(window)
    assert worker2 is not None and window._calls["worker_start"] == 2


def test_case_g_after_error_state_is_released(window):
    """Case G：unexpected error 后状态释放，可重新开始。"""
    _started_worker(window)
    window._handle_unexpected_error("模拟启动失败")
    assert window._run_in_progress is False
    assert window.start_button.isEnabled() is True
    _started_worker(window)
    assert window._calls["worker_start"] == 2


def test_case_h_after_cancel_state_is_released(window):
    """Case H：取消后状态释放，可重新开始。"""
    _started_worker(window)
    window._cancel_run()
    assert window._run_in_progress is True, "cancelling 期间仍拒绝新 run"
    window._start_run()
    assert window._calls["worker_start"] == 1, "cancelling 期间不得启动新 run"
    _release_after_result(window)  # 模拟取消完成后 worker 收尾
    assert window._run_in_progress is False
    _started_worker(window)
    assert window._calls["worker_start"] == 2


def test_case_i_exception_before_worker_start_releases_guard(window, monkeypatch):
    """Case I：准备阶段在 worker.start 前抛异常 → guard 释放，可再次开始。"""
    def broken_save_asr(**kwargs):
        raise RuntimeError("配置保存失败")

    monkeypatch.setattr(window, "_save_asr_configuration", broken_save_asr)
    with pytest.raises(RuntimeError):
        window._start_run()
    assert window._run_in_progress is False, "启动前异常必须释放 guard"
    assert window.start_button.isEnabled() is True

    monkeypatch.setattr(window, "_save_asr_configuration", lambda **kw: True)
    _started_worker(window)
    assert window._calls["worker_start"] == 1


def test_case_j_no_valid_input_releases_guard(window, monkeypatch):
    """Case J：无有效输入提前返回 → guard 释放，不锁死（按钮随素材状态）。"""
    window.media_paths = []
    monkeypatch.setattr("twobyteasr.app.ui.QMessageBox.information", lambda *a, **k: None)
    window._start_run()
    assert window._run_in_progress is False, "验证提前返回必须释放 guard"
    # 无素材时开始按钮本来就应禁用（与素材状态一致，非锁死）；
    # 恢复素材后（fixture 中 _refresh_media_summary 为 no-op，直接模拟刷新）按钮恢复。
    window.media_paths = ["dummy.mp4"]
    window.start_button.setEnabled(True)
    assert window.start_button.isEnabled() is True
    _started_worker(window)
    assert window._calls["worker_start"] == 1


def test_start_button_disabled_during_run_and_restored(window):
    """运行期间开始按钮禁用；释放后恢复（UI 层防护）。"""
    assert window.start_button.isEnabled() is True
    _started_worker(window)
    assert window.start_button.isEnabled() is False, "运行期间开始按钮必须禁用"
    _release_after_result(window)
    assert window.start_button.isEnabled() is True


def test_worker_finished_is_idempotent_fallback_release(window):
    """P1-4 兜底：finished 信号幂等释放（try 外异常路径不锁死 UI）。"""
    _started_worker(window)
    assert window._run_in_progress is True
    # 模拟 run() 中 try 外异常：只有 finished、没有 result_ready/unexpected_error
    window.worker.finished.emit()
    assert window._run_in_progress is False
    assert window.start_button.isEnabled() is True
    # 再次触发（如 finish 后 _handle_result 也执行）→ 幂等，无异常
    window.worker.finished.emit()
    assert window._run_in_progress is False


def test_smoke_real_mainwindow_start_duplicate_cancel_restart(monkeypatch):
    """UI 层 smoke：真实 MainWindow 上 开始→快速重复→取消→再开始。

    全程只有一条 worker 生命周期；重复调用不覆盖 token/worker。
    """
    import subtitle_core as legacy

    win = MainWindow([], legacy, _FakePipeline(), None)
    monkeypatch.setattr("twobyteasr.app.ui.QMessageBox.information", lambda *a, **k: None)
    monkeypatch.setattr(win, "_ensure_cuda_runtime", lambda: True)
    monkeypatch.setattr(win, "_ensure_runtime_environment", lambda: True)
    monkeypatch.setattr(win, "_save_asr_configuration", lambda **kw: True)
    monkeypatch.setattr(win, "_save_ai_configuration", lambda **kw: True)
    monkeypatch.setattr(win, "_show_task_notification", lambda *a, **k: None)
    monkeypatch.setattr("twobyteasr.app.ui.apply_ui_language", lambda *a, **k: None)
    monkeypatch.setattr(PipelineWorker, "start", lambda self: None)
    win.media_paths = ["dummy.mp4"]
    win.show()

    win._start_run()
    worker1, token1 = win.worker, win.token
    assert win._run_in_progress is True
    assert win.start_button.isEnabled() is False

    win._start_run()  # 快速重复点击
    win._start_run()
    assert win.worker is worker1, "重复调用不得覆盖 worker"
    assert win.token is token1, "重复调用不得覆盖 token"

    win._cancel_run()
    assert win._run_in_progress is True, "cancelling 期间仍拒绝新 run"
    win._start_run()
    assert win.worker is worker1

    win._handle_result(QueueResult((MediaResult("dummy.mp4", "cancelled"),), 1.0))
    assert win._run_in_progress is False
    assert win.start_button.isEnabled() is True

    win._start_run()  # 取消完成后可再次开始
    assert win.worker is not worker1
    win._handle_result(QueueResult((MediaResult("dummy.mp4", "success"),), 1.0))
    win.close()
    app.processEvents()
