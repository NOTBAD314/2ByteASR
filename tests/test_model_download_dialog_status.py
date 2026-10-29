"""Download window wording for the 2026-10-14 mainland round: whole-model progress,
current source, automatic source switch, resume, reuse and final verification."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.local_models.model_workshop import MODELS, ModelDownloadDialog

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import reset_runtime_paths, MODEL_ROOT_ENV, USER_DATA_ENV
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(tmp_path / 'models'))
    monkeypatch.setenv(USER_DATA_ENV, str(tmp_path / 'local'))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _line(prefix, **payload):
    return f"{prefix} {json.dumps(payload, ensure_ascii=False)}"


def _dialog():
    QApplication.instance() or QApplication([])
    model = next(model for model in MODELS if model.download_key == 'funasr_nano')
    return ModelDownloadDialog(ROOT, model)


def test_hidden_bridge_delivers_sparse_output_while_child_is_still_running(tmp_path):
    import sys,time
    from PySide6.QtCore import QProcess
    from PySide6.QtTest import QTest
    from twobyteasr.local_models.model_workshop import _HiddenProcessBridge
    app=QApplication.instance() or QApplication([])
    bridge=_HiddenProcessBridge()
    bridge.setWorkingDirectory(str(tmp_path))
    bridge.start(sys.executable,['-I','-u','-c',"import time;print('SPARSE_PHASE',flush=True);time.sleep(5)"])
    received=b''
    try:
        deadline=time.monotonic()+2
        while time.monotonic()<deadline and b'SPARSE_PHASE' not in received:
            QTest.qWait(30)
            received+=bytes(bridge.readAllStandardOutput())
        assert b'SPARSE_PHASE' in received
        assert bridge.state()==QProcess.ProcessState.Running
    finally:
        bridge.kill()
        bridge.waitForFinished(3000)
        QTest.qWait(50)


def test_next_weight_file_leaves_the_previous_file_verification_phase():
    dialog=_dialog()
    dialog._handle_progress_line(_line('[2BYTEASR_PROGRESS]',phase='verify',percent=100,downloaded=100,total=100,speed=0))
    assert dialog._phase=='files_verifying'
    dialog._handle_progress_line(_line('[2BYTEASR_PROGRESS]',phase='download',percent=20,downloaded=200,total=1000,speed=100))
    assert dialog._phase=='weights_downloading'
    dialog._phase='files_verifying'
    dialog._handle_progress_line(_line('[2BYTEASR_FILE]',file='config.json',index=2,total=3,phase='downloading'))
    assert dialog._phase=='weights_downloading'
    dialog.close()


def test_uv_build_backend_timeout_is_not_reported_as_a_version_conflict():
    dialog=_dialog()
    dialog.log.appendPlainText('[运行库] uv pip install local-moss\nNo solution found when resolving setuptools, wheel\nFailed to fetch https://pypi.org/simple/wheel/\noperation timed out')
    dialog.log.appendPlainText(_line('[2BYTEASR_INSTALL_ERROR]',phase='dependencies_installing',message='子程序退出码 1'))
    message=dialog._actionable_failure_message(1)
    assert '超时' in message
    assert '依赖版本冲突' not in message
    assert 'TUN' not in message
    dialog.close()

def test_status_shows_source_switch_reuse_whole_model_progress_resume_and_verification():
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co',
               attempt=1, total=2, status='trying'))
    feed(_line('[2BYTEASR_FILE]', file='Qwen3-0.6B/config.json', index=1, total=10, phase='downloading'))
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co',
               attempt=1, total=2, status='failed', category='network_timeout'))
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='trying'))
    text = dialog.progress_status.text()
    assert 'Hugging Face 官方 没有完成（连接超时），自动改试 HF 镜像（可能回源官方）（hf-mirror.com）' in text
    assert '第 2/2 个来源' in text

    feed(_line('[2BYTEASR_CACHE]', file='multilingual.tiktoken', bytes=1_000_000, origin='verified staging', network_bytes=0))
    assert '已沿用校验过的文件：multilingual.tiktoken' in dialog.progress_status.text()

    feed(_line('[2BYTEASR_FILE]', file='model.pt', index=9, total=10, phase='downloading'))
    feed(_line('[2BYTEASR_FILE]', file='model.pt', size=1_971_149_431))
    feed(_line('[2BYTEASR_PROGRESS]', percent=50, downloaded=985_574_715, total=1_971_149_431,
               speed=20 * 1024 ** 2, phase='download'))
    text = dialog.progress_status.text()
    assert '整个模型 0.92 / 1.85 GiB（49%）' in text and '剩余约' in text
    assert '来源：HF 镜像（可能回源官方） (hf-mirror.com)  ·  第 2/2 个来源' in text
    assert dialog.progress.value() == 49

    feed('第 1 次中断（已有进展，保留断点续传），1.0 秒后重试：Connection broken')
    feed(_line('[2BYTEASR_PROGRESS]', percent=60, downloaded=1_182_689_658, total=1_971_149_431,
               speed=20 * 1024 ** 2, phase='download'))
    assert '网络中断，已从断点续传（第 1 次）' in dialog.progress_status.text()
    feed('[重试] model.pt：来源暂时没有响应（network_timeout），4 秒后第 1 次重试；已下载部分保留')
    assert '来源暂时没有响应，稍后自动重试（第 2 次），已下载的部分保留' in dialog.progress_status.text()

    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='selected'))
    assert dialog._source_detail_line().endswith('全部文件已通过 SHA-256 校验，与锁定版本一致')
    dialog.deleteLater()


def test_failure_after_every_source_explains_what_the_user_can_do():
    dialog = _dialog()
    for line in (
        _line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co', attempt=1, total=2, status='trying'),
        _line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com', attempt=2, total=2, status='trying'),
        _line('[2BYTEASR_ERROR]', model='funasr_nano', phase='weights_downloading', category='network_timeout',
              detail='HF_OFFICIAL: Read timed out；HF_MIRROR: Read timed out'),
    ):
        dialog.log.appendPlainText(line)
    message = dialog._actionable_failure_message(1)
    assert 'Hugging Face 官方 → HF 镜像（可能回源官方）（已尝试备援）' in message
    assert '所有下载来源都没有连通' in message and '继续重试' in message
    assert 'HF_OFFICIAL →' not in message
    dialog.deleteLater()


def test_page_file_failure_says_what_to_change_not_that_the_model_is_broken():
    """2026-10-15 report: the aligner load hit Windows' commit limit (os error 1455)."""
    dialog = _dialog()
    for line in (
        _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', label='ModelScope', host='modelscope.cn', attempt=1, total=1, status='trying'),
        _line('[2BYTEASR_INSTALL_ERROR]', phase='model_loading', category='system_memory',
              message='[2BYTEASR_QWEN3_ALIGNER] {"event": "failed", "detail": "页面文件太小，无法完成操作。 (os error 1455)"}'),
    ):
        dialog.log.appendPlainText(line)
    message = dialog._actionable_failure_message(1)
    assert '虚拟内存' in message and '系统管理的大小' in message and '继续重试' in message
    assert 'os error 1455' in message and '模型加载失败' not in message
    dialog.deleteLater()


def test_runtime_preparation_lines_show_what_is_happening_not_model_verification():
    dialog = _dialog()
    dialog._phase = 'tools_preparing'
    dialog._handle_progress_line('[工具] 获取固定版本 uv 0.11.7，每个来源都校验 SHA-256')
    assert dialog.progress_status.text() == '获取固定版本 uv 0.11.7，每个来源都校验 SHA-256'
    dialog._handle_progress_line('[工具] GitHub 未成功（curl exit 28）')
    assert dialog.progress_status.text() == 'GitHub 未成功（curl exit 28）'
    dialog._handle_progress_line('uv.exe SHA-256 ok')
    assert '模型文件' not in dialog.progress_status.text()
    dialog._phase = 'weights_downloading'
    dialog._handle_progress_line('SHA-256 校验中')
    assert dialog.progress_status.text() == '正在校验模型文件完整性…'
    dialog.deleteLater()


def test_downloader_per_file_lines_do_not_replace_model_level_source_or_file_count():
    # Real window, mainland run 2026-10-14: per-file events showed "HF_MIRROR" and "文件 16 / 16".
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='trying'))
    feed(_line('[2BYTEASR_FILE]', file='model.pt', index=9, total=10, phase='downloading'))
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', host='hf-mirror.com', attempt=1, total=1, status='trying',
               url='https://hf-mirror.com/FunAudioLLM/Fun-ASR-Nano-2512/resolve/x/model.pt'))
    feed(_line('[2BYTEASR_FILE]', file='model.pt', size=1_971_149_431))
    feed(_line('[2BYTEASR_PROGRESS]', percent=10, downloaded=197_114_943, total=1_971_149_431,
               speed=8 * 1024 ** 2, phase='download'))
    text = dialog.progress_status.text()
    assert '文件 9 / 10' in text
    assert '来源：HF 镜像（可能回源官方） (hf-mirror.com)  ·  第 2/2 个来源' in text
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', host='hf-mirror.com', attempt=1, total=1, status='selected',
               url='https://hf-mirror.com/FunAudioLLM/Fun-ASR-Nano-2512/resolve/x/model.pt'))
    assert 'SHA-256 校验' not in dialog._source_detail_line()  # one file done is not the whole model
    dialog.deleteLater()


def test_label_less_source_events_show_a_readable_name():
    dialog = _dialog()
    dialog._handle_progress_line(_line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', host='huggingface.co', attempt=1,
                                       total=1, status='trying', url='https://huggingface.co/x/resolve/r/model.pt'))
    assert 'HF_OFFICIAL' not in dialog.progress_status.text()
    assert 'Hugging Face 官方' in dialog.progress_status.text()
    dialog.deleteLater()


def test_downloader_source_line_carries_the_label():
    import importlib.util
    import io
    from contextlib import redirect_stdout
    spec = importlib.util.spec_from_file_location('dff_label', ROOT / 'scripts' / 'download_file_fast.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        module._emit_source_line('https://hf-mirror.com/a/resolve/b/c.bin', 'HF_MIRROR', 1, 1, 'trying')
    payload = json.loads(buffer.getvalue().split(' ', 1)[1])
    assert payload['label'] == 'HF 镜像（可能回源官方）' and payload['host'] == 'hf-mirror.com'


def test_reuse_note_clears_when_the_next_file_starts():
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='HF_MIRROR', label='HF 镜像（可能回源官方）', host='hf-mirror.com',
               attempt=2, total=2, status='trying'))
    feed(_line('[2BYTEASR_CACHE]', file='configuration.json', bytes=398, origin='verified staging', network_bytes=0))
    assert '已沿用' in dialog._source_detail_line()
    feed(_line('[2BYTEASR_FILE]', file='model.pt', index=9, total=10, phase='downloading'))
    assert '已沿用' not in dialog._source_detail_line()
    dialog.deleteLater()


def test_runtime_command_echo_and_paths_stay_in_the_raw_log():
    dialog = _dialog()
    dialog._phase = 'dependencies_installing'
    dialog._handle_progress_line('[运行库] 改用 阿里云 PyPI 镜像 + 上海交大 PyTorch 镜像；每个包都按锁定 SHA-256 校验')
    before = dialog.progress_status.text()
    dialog._handle_progress_line(r'[运行库] C:\Users\x\runtimes\tools\uv-0.11.7\uv.exe --no-config pip install --python C:\x\python.exe')
    assert dialog.progress_status.text() == before
    dialog._handle_progress_line(r'[运行库] 复用已验证环境 C:\Users\x\runtimes\main\5d274a7c')
    assert dialog.progress_status.text() == '复用已验证环境'
    dialog.deleteLater()


def test_no_remaining_time_from_tiny_config_files():
    dialog = _dialog()
    feed = dialog._handle_progress_line
    feed(_line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', label='ModelScope', host='modelscope.cn', attempt=1, total=3, status='trying'))
    feed(_line('[2BYTEASR_FILE]', file='merges.txt', index=3, total=6, phase='downloading'))
    feed(_line('[2BYTEASR_FILE]', file='merges.txt', size=1_671_853))
    feed(_line('[2BYTEASR_PROGRESS]', percent=1, downloaded=20_000, total=1_671_853, speed=266, phase='download'))
    assert '剩余约' not in dialog.progress_status.text()
    dialog.deleteLater()


def test_runtime_pytorch_download_shows_progress_source_and_switch():
    # 0.7.1 user, 2026-10-14: "Downloading torch (2.4GiB)" and then nothing for minutes.
    dialog = _dialog()
    feed = dialog._handle_progress_line
    gib = 1024 ** 3
    base = dict(file='torch-2.11.0+cu126-cp310-cp310-win_amd64.whl', package='torch', index=1, count=2,
                total=2 * int(1.2 * gib))
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', **base, downloaded=base['total'] // 2, speed=1024 ** 2,
               source='PyTorch 官方', host='download.pytorch.org', phase='download'))
    text = dialog.progress_status.text()
    assert text.splitlines()[0] == '正在下载运行环境：PyTorch（1/2）'
    assert '1.20 GiB / 2.40 GiB  ·  50%  ·  1.0 MB/s  ·  剩余约 20 分 28 秒' in text
    assert '来源：PyTorch 官方（download.pytorch.org）' in text
    assert (dialog.progress.maximum(), dialog.progress.value()) == (100, 50)
    trying = {'kind': 'trying', 'from': 'PyTorch 官方', 'to': '上海交大 PyTorch 镜像', 'from_rate': 0.9 * 1024 ** 2, 'offset': 1}
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', **base, downloaded=base['total'] // 2, speed=8 * 1024 ** 2,
               source='上海交大 PyTorch 镜像', host='mirror.sjtu.edu.cn', phase='download', event=trying))
    assert 'PyTorch 官方 最近只有 0.9 MB/s，正在试用 上海交大 PyTorch 镜像' in dialog.progress_status.text()
    event = {'kind': 'switched', 'from': 'PyTorch 官方', 'to': '上海交大 PyTorch 镜像',
             'from_rate': 0.9 * 1024 ** 2, 'to_rate': 15 * 1024 ** 2, 'offset': base['total'] // 2}
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', **base, downloaded=int(1.5 * gib), speed=15 * 1024 ** 2,
               source='上海交大 PyTorch 镜像', host='s3.jcloud.sjtu.edu.cn', phase='download', event=event))
    text = dialog.progress_status.text()
    assert '来源：上海交大 PyTorch 镜像（s3.jcloud.sjtu.edu.cn）' in text
    assert 'PyTorch 官方 只有 0.9 MB/s，已改用 上海交大 PyTorch 镜像（15.0 MB/s），从 1.20 GiB 处继续' in text
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', **base, downloaded=int(2.4 * gib), source='上海交大 PyTorch 镜像',
               host='s3.jcloud.sjtu.edu.cn', phase='verify'))
    assert dialog.progress_status.text().startswith('正在校验 PyTorch 的 SHA-256…')
    assert dialog.progress.maximum() == 0  # busy while hashing
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', **base, downloaded=int(2.4 * gib), source='上海交大 PyTorch 镜像',
               host='s3.jcloud.sjtu.edu.cn', phase='done'))
    assert dialog.progress_status.text().startswith('PyTorch 已下载并通过 SHA-256 校验，继续安装运行环境…')
    assert dialog.progress.maximum() == 0  # uv still installs; no false 100 %
    failed = {'kind': 'failed', 'from': 'PyTorch 官方', 'to': '南京大学 PyTorch 镜像', 'offset': 0}
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', **dict(base, package='torchaudio', index=2, total=1_519_595), downloaded=1000,
               speed=0, source='南京大学 PyTorch 镜像', host='mirror.nju.edu.cn', phase='download', event=failed))
    text = dialog.progress_status.text()
    assert text.splitlines()[0] == '正在下载运行环境：torchaudio（2/2）'
    assert 'PyTorch 官方 未成功，已改用 南京大学 PyTorch 镜像，从 0.0 MiB 处继续' in text
    dialog.deleteLater()


def test_runtime_download_lines_drive_progress_but_stay_out_of_the_raw_log():
    dialog = _dialog()
    marker = _line('[2BYTEASR_RUNTIME_DOWNLOAD]', file='torch.whl', package='torch', index=1, count=2,
                   downloaded=10 << 20, total=100 << 20, speed=1 << 20, source='PyTorch 官方',
                   host='download.pytorch.org', phase='download')
    readable = '[PyTorch] torch 已下载 10%（10.0 MiB / 100.0 MiB）'
    chunks = [(marker + '\n' + readable + '\n').encode('utf8')]
    dialog.process.readAllStandardOutput = lambda: chunks.pop() if chunks else b''
    dialog._read_output()
    log = dialog.log.toPlainText()
    assert readable in log and '[2BYTEASR_RUNTIME_DOWNLOAD]' not in log
    assert dialog._last_log_at > 0  # "最后日志" counts these lines as activity
    assert '10%' in dialog.progress_status.text()
    dialog.deleteLater()


def test_pause_message_says_what_a_retry_really_resumes():
    dialog = _dialog()
    dialog._paused = True
    dialog._finished_v2(1, None)
    text = dialog.progress_status.text()
    assert text == '任务已暂停。重试时先校验已有文件：模型权重和 PyTorch 安装包从断点继续下载，已完成的依赖直接复用。'
    assert '复用分片' not in text
    dialog.deleteLater()


def test_source_choice_explains_the_runtime_sources():
    dialog = _dialog()
    tip = dialog.source_combo.toolTip()
    assert 'ModelScope 或 HF 镜像' in tip and '运行环境' in tip and 'SHA-256' in tip
    dialog.deleteLater()


def _running(dialog, monkeypatch, started_ago=200.0):
    """Pretend the installer runs; returns the run's monotonic start."""
    import time
    from PySide6.QtCore import QProcess
    monkeypatch.setattr(dialog.process, 'state', lambda: QProcess.ProcessState.Running)
    monkeypatch.setattr(dialog.process, 'processId', lambda: 0)
    start = time.monotonic() - started_ago
    dialog._started_at = start
    dialog._activity.reset(start, time.time() - started_ago)
    return start


def test_heartbeats_are_not_progress_and_an_idle_silent_step_says_where_and_why(monkeypatch):
    # User report 2026-10-21: "最后日志：0 秒前" stayed fresh because the supervisors
    # print a heartbeat every 15 s, so a stuck dependency install looked alive.
    dialog = _dialog()
    dialog._modelscope_cache = True  # every selected model is on ModelScope
    start = _running(dialog, monkeypatch)
    feed = dialog._activity.feed
    feed(_line('[2BYTEASR_PHASE]', phase='dependencies_installing'), start + 1, 0)
    feed(_line('[2BYTEASR_DEPLOY]', phase='dependencies_installing', state='start', component='main',
               attempt=1, source='PyPI 官方'), start + 1, 0)
    for second in range(16, 200, 15):
        feed(_line('[2BYTEASR_DEPLOY]', phase='dependencies_installing', state='waiting', component='下载并安装依赖',
                   elapsed_s=second, output_age_s=second, waiting='subprocess'), start + second, 0)
    for second in range(100, 200):  # the whole process tree is idle
        dialog._activity.tick(start + second, {'cpu': 0.0, 'io': 0.0})
    dialog._refresh_view(start + 200)
    assert '最后进展：3 分 19 秒前' in dialog.activity_status.text()
    assert dialog.note_label.text().startswith('已用 3 分 20 秒 · 第 2/4 步')
    assert dialog.health_pill.text() == '可能卡住' and dialog.health_pill.property('tone') == 'bad'
    assert dialog.notice.isVisibleTo(dialog)
    assert '没有进展，子程序也几乎没有活动' in dialog.notice_title.text()
    assert '卡在：运行环境 · 安装依赖（main 环境）' in dialog.notice_where.text()
    assert 'PyPI 官方' in dialog.notice_body.text()
    actions = [dialog.notice_buttons.itemAt(index).widget() for index in range(dialog.notice_buttons.count())]
    assert [button.property('noticeAction') for button in actions] == ['switch:MODELSCOPE', 'export']
    assert actions[0].text() == '改用 ModelScope 继续'
    # The same silence while the tree unpacks and writes is work, not a stall.
    for second in range(200, 260):
        dialog._activity.tick(start + second, {'cpu': 60.0, 'io': 40 << 20})
    dialog._refresh_view(start + 260)
    assert dialog.health_pill.text() == '仍在工作'
    assert not dialog.notice.isVisibleTo(dialog)
    dialog.deleteLater()


def test_measured_download_fills_the_task_bar_and_steps_never_bounce(monkeypatch):
    dialog = _dialog()
    start = _running(dialog, monkeypatch, 30)
    feed = dialog._activity.feed
    feed(_line('[2BYTEASR_PHASE]', phase='tools_preparing'), start + 1, 0)
    feed(_line('[2BYTEASR_RUNTIME_DOWNLOAD]', file='torch.whl', package='torch', index=1, count=2,
               downloaded=512 << 20, total=2048 << 20, speed=8 << 20, source='上海交大 PyTorch 镜像',
               host='mirror.sjtu.edu.cn', phase='download'), start + 29, 0)
    dialog._refresh_view(start + 30)
    assert dialog.task_title.text() == '下载 PyTorch（1/2）'
    assert dialog.task_bar.isVisibleTo(dialog) and dialog.task_bar.value() == 250
    assert '512.0 MiB / 2.00 GiB' in dialog.task_figures.text() and '8.0 MB/s' in dialog.task_figures.text()
    assert dialog.task_source.text() == '来源：上海交大 PyTorch 镜像（mirror.sjtu.edu.cn）'
    states = [state for _key, _label, state, _note, _fraction in dialog.step_track.rows()]
    assert states == ['done', 'active', 'pending', 'pending']
    assert dialog.health_pill.text() == '正常进行'
    assert dialog.background_summary() == '第 2/4 步 · 运行环境 · 25%'  # the workshop page line
    # The legacy bar keeps its busy semantics for scripts, but is never shown.
    assert not dialog.progress.isVisibleTo(dialog)
    dialog.deleteLater()


def test_switching_source_stops_then_continues_with_the_chosen_source(monkeypatch):
    from PySide6.QtCore import QProcess
    dialog = _dialog()
    _running(dialog, monkeypatch)
    stops, starts = [], []
    monkeypatch.setattr(dialog, '_request_pause', lambda: stops.append(True))
    monkeypatch.setattr(dialog, 'start', lambda: starts.append(dialog.source_combo.currentData()))
    dialog._switch_source_and_resume('MODELSCOPE')
    assert stops == [True] and dialog._resume_with_source == 'MODELSCOPE'
    monkeypatch.setattr(dialog.process, 'state', lambda: QProcess.ProcessState.NotRunning)
    dialog._paused = True
    dialog._finished_v2(1, None)
    QApplication.processEvents()
    from PySide6.QtTest import QTest
    QTest.qWait(400)
    assert starts == ['MODELSCOPE']
    assert dialog.headline.text().startswith('已暂停')
    dialog.deleteLater()


def test_failure_names_the_step_and_keeps_the_installer_advice(monkeypatch):
    dialog = _dialog()
    start = _running(dialog, monkeypatch)
    dialog._activity.feed(_line('[2BYTEASR_PHASE]', phase='model_loading', model='funasr_nano'), start + 5, 0)
    from PySide6.QtCore import QProcess
    monkeypatch.setattr(dialog.process, 'state', lambda: QProcess.ProcessState.NotRunning)
    dialog._finished_v2(1, None)
    assert dialog.health_pill.text() == '未完成'
    assert dialog.notice.isVisibleTo(dialog) and dialog.notice.property('tone') == 'bad'
    assert not dialog.task_card.isVisibleTo(dialog)  # the notice says it once
    assert dialog.notice_title.text() == '没有完成：加载试跑'
    assert dialog.notice_where.text().startswith('停在：加载试跑')
    assert dialog.notice_body.text() == dialog.progress_status.text()
    assert dialog.headline.text().endswith('没有准备完成')
    states = [state for _key, _label, state, _note, _fraction in dialog.step_track.rows()]
    assert states == ['done', 'done', 'done', 'failed']
    dialog.deleteLater()


def test_recent_events_are_listed_without_opening_the_raw_log(monkeypatch):
    dialog = _dialog()
    start = _running(dialog, monkeypatch)
    feed = dialog._activity.feed
    feed('[工具] GitHub 官方 未成功（连接或传输超时）', start + 1, 1_800_000_000)
    feed('Resolved 104 packages in 5.08s', start + 2, 1_800_000_001)
    feed('Prepared 104 packages in 34.54s', start + 3, 1_800_000_002)
    dialog._refresh_view(start + 4)
    texts = [text.text() for _stamp, _dot, text in dialog._event_rows if text.isVisibleTo(dialog)]
    assert texts == ['GitHub 官方 未成功（连接或传输超时）', '依赖下载完成（104 个）']
    assert dialog._event_rows[0][2].property('tone') == 'bad'
    assert not dialog.log.isVisibleTo(dialog)
    dialog.deleteLater()


def test_log_keeps_the_readers_place_and_follows_only_at_the_bottom():
    # User report 2026-10-14: while MOSS downloaded, every new line pulled the
    # log back to the bottom, so earlier lines could not be read.
    dialog = _dialog()
    dialog.resize(900, 640)
    dialog.show()
    dialog.log_toggle.setChecked(True)  # the raw log is collapsed by default
    QApplication.processEvents()
    chunks = []
    dialog.process.readAllStandardOutput = lambda: chunks.pop(0) if chunks else b''

    def feed(first, count):
        chunks.append(''.join(f'line {n}\n' for n in range(first, first + count)).encode('utf8'))
        dialog._read_output()
        QApplication.processEvents()

    feed(0, 300)
    bar = dialog.log.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    selection = dialog.log.textCursor()  # the reader selects some text...
    selection.setPosition(5)
    selection.setPosition(12, selection.MoveMode.KeepAnchor)
    dialog.log.setTextCursor(selection)
    bar.setValue(10)  # ...and scrolls up
    feed(300, 60)
    assert bar.value() == 10
    assert dialog.log.textCursor().selectionStart() == 5 and dialog.log.textCursor().selectionEnd() == 12
    assert dialog.log.toPlainText().rstrip().endswith('line 359')
    bar.setValue(bar.maximum())  # back at the bottom: follow again
    feed(360, 60)
    assert bar.value() == bar.maximum() and dialog.log.toPlainText().rstrip().endswith('line 419')
    dialog.deleteLater()
