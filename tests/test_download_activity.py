"""Download window model (2026-10-21): steps, measured figures and stall diagnosis.

The line formats are the installer's real output (first-deployment runs of
2026-10-20/21: uv, PyTorch wheels, ModelScope weights, model loading).
"""
import json
import subprocess
import sys
import time

from twobyteasr.local_models.download_activity import DownloadActivity, ProcessTreeProbe, host_region


def _line(prefix, **payload):
    return f"{prefix} {json.dumps(payload, ensure_ascii=False)}"


def _run(lines, names=None):
    """Feed (second, line) pairs; returns the model."""
    activity = DownloadActivity(names or {'moss': 'MOSS', 'qwen_asr': 'Qwen3-ASR'})
    activity.reset(0.0, 1_800_000_000.0)
    for second, line in lines:
        activity.feed(line, float(second), 1_800_000_000.0 + second)
    return activity


def _states(activity, now=0.0):
    return [state for _key, _label, state, _note, _fraction in activity.step_rows(now)]


def test_steps_follow_the_installer_and_never_move_backwards():
    activity = _run([
        (0, _line('[2BYTEASR_PHASE]', phase='preparing')),
        (1, _line('[2BYTEASR_PHASE]', phase='tools_preparing')),
        (2, _line('[2BYTEASR_PHASE]', phase='interpreter_preparing')),
        (3, _line('[2BYTEASR_PHASE]', phase='dependencies_installing')),
        (4, _line('[2BYTEASR_PHASE]', phase='environment_checking')),
        (5, '[运行库] 复用已验证环境 C:\\Users\\x\\runtimes\\main\\abc'),
        (6, _line('[2BYTEASR_PHASE]', phase='runtime_ready')),
        (7, '[下载] Qwen/Qwen3-ASR-1.7B @ 7278e1e7'),
        (8, _line('[2BYTEASR_PHASE]', phase='weights_downloading')),
        # a second environment repeats an earlier phase: the track stays put
        (9, _line('[2BYTEASR_PHASE]', phase='interpreter_preparing')),
    ])
    assert activity.step == 'weights'
    assert _states(activity, 9) == ['done', 'done', 'active', 'pending']
    rows = activity.step_rows(9)
    assert rows[1][3] == '沿用'
    activity.mark_finished('done', 10)
    assert _states(activity, 10) == ['done', 'done', 'done', 'done']


def test_uv_output_becomes_package_progress():
    activity = _run([
        (0, _line('[2BYTEASR_PHASE]', phase='dependencies_installing')),
        (0, _line('[2BYTEASR_DEPLOY]', phase='dependencies_installing', state='start', component='main', attempt=1,
                  source='阿里云 PyPI 镜像')),
        (0, '[运行库] 阿里云 PyPI 镜像（1/5）；固定版本与 SHA-256 校验；只允许已声明的纯 Python 源码包构建'),
        (5, 'Resolved 104 packages in 5.08s'),
        (5, 'Downloading scipy (39.3MiB)'),
        (5, 'Downloading numpy (12.3MiB)'),
        (5, '   Building textgrid==1.6.1'),
        (9, ' Downloaded numpy'),
    ])
    assert activity.task_title() == '安装依赖（main 环境）'
    assert activity.figures(10).startswith('已下载 1/2 个较大的依赖（12.3 MiB / 51.6 MiB）')
    assert '共 104 个依赖' in activity.figures(10)
    assert round(activity.task_fraction(), 3) == round(12.3 / 51.6, 3)
    assert activity.source_line() == '来源：阿里云 PyPI 镜像  ·  第 1/5 个来源'
    activity.feed('Prepared 104 packages in 34.54s', 30.0, 0)
    assert activity.task_title() == '安装 104 个依赖（main 环境）'
    assert activity.task_fraction() == 1.0
    assert activity.events_tail(1)[0].text == '依赖下载完成（104 个）'


def test_heartbeats_alone_do_not_count_as_progress():
    lines = [(0, _line('[2BYTEASR_DEPLOY]', phase='model_loading', state='start', component='moss'))]
    lines += [(second, _line('[2BYTEASR_DEPLOY]', phase='model_loading', state='waiting', component='moss',
                             elapsed_s=second, output_age_s=second, waiting='subprocess')) for second in range(15, 181, 15)]
    activity = _run(lines)
    assert activity.last_progress_at == 0.0
    assert activity.task_title() == '加载 MOSS 并用样本试跑'
    # no probe samples at all: the silent thresholds double before a verdict
    assert activity.assess(119, running=True).level == 'ok'
    assert activity.assess(181, running=True).level == 'quiet'


def test_a_download_without_new_bytes_is_first_waiting_then_stuck_with_a_way_out():
    lines = [(0, _line('[2BYTEASR_PHASE]', phase='dependencies_installing'))]
    lines += [(second, _line('[2BYTEASR_RUNTIME_DOWNLOAD]', file='torch.whl', package='torch', index=1, count=2,
                             downloaded=second * (4 << 20), total=2 << 30, speed=4 << 20, source='PyTorch 官方',
                             host='download.pytorch.org', phase='download')) for second in range(1, 41)]
    activity = _run(lines)
    assert activity.assess(45, running=True).level == 'ok'
    quiet = activity.assess(61, running=True)
    assert (quiet.level, quiet.pill) == ('quiet', '等待回应')
    stuck = activity.assess(101, running=True, mode='AUTO')
    assert (stuck.level, stuck.tone) == ('stalled', 'bad')
    assert stuck.headline == '已经 1 分 1 秒没有收到新的数据'
    assert stuck.where.startswith('卡在：运行环境 · 下载 PyTorch（1/2）')
    assert 'download.pytorch.org' in stuck.where
    assert '没有开代理' in stuck.why and '国内来源' in stuck.why
    assert stuck.actions == ('switch:MODELSCOPE', 'export')
    # Already on a domestic choice: nothing to switch to for the runtime.
    assert activity.assess(101, running=True, mode='MODELSCOPE').actions == ('export',)
    assert activity.assess(101, running=True, mode='AUTO', modelscope_ok=False).actions[0] == 'switch:HF_MIRROR'


def test_the_last_bytes_of_a_big_file_are_hashing_not_a_stall():
    total = 4 << 30
    lines = [(0, '[下载] Qwen/Qwen3-ASR-1.7B @ 7278e1e7'),
             (0, _line('[2BYTEASR_FILE]', file='model-00001-of-00002.safetensors', index=3, total=10, phase='downloading')),
             (1, _line('[2BYTEASR_FILE]', file='model-00001-of-00002.safetensors', size=total))]
    lines += [(second, _line('[2BYTEASR_PROGRESS]', percent=99, downloaded=total - (8 << 20), total=total,
                             speed=100 << 20, phase='download')) for second in (40,)]
    activity = _run(lines)
    # 30 s without bytes right at the end of the file: the downloader hashes 4 GiB.
    assert activity.assess(70, running=True).level == 'ok'


def test_last_file_selected_means_the_whole_model_is_being_verified():
    activity = _run([
        (0, '[下载] Qwen/Qwen3-ASR-1.7B @ 7278e1e7'),
        (0, _line('[2BYTEASR_FILE]', file='vocab.json', index=10, total=10, phase='downloading')),
        (1, _line('[2BYTEASR_FILE]', file='vocab.json', size=2776833)),
        (1, _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', host='modelscope.cn', label='ModelScope',
                  url='https://modelscope.cn/api', attempt=1, total=1, status='selected')),
    ])
    assert activity.task.kind == 'files_verify'
    assert activity.task_title() == '校验 Qwen/Qwen3-ASR-1.7B 的全部文件'
    assert activity.assess(40, running=True).level == 'ok'


def test_weights_progress_counts_reused_files_and_only_grows():
    activity = _run([
        (0, '- 需下载 2 个模型：moss、qwen_asr'),
        (0, '- 预计下载约 2.00 GiB；建议至少保留 2.1 GiB 可用空间。'),
        (1, '[下载] OpenMOSS-Team/MOSS-Transcribe-Diarize @ e6d68cdf'),
        (1, _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', label='ModelScope', host='modelscope.cn', attempt=1, total=3,
                  status='trying')),
        (1, _line('[2BYTEASR_CACHE]', file='tokenizer.json', bytes=256 << 20, origin='verified staging')),
        (2, _line('[2BYTEASR_FILE]', file='model.safetensors', index=17, total=17, phase='downloading')),
        (2, _line('[2BYTEASR_FILE]', file='model.safetensors', size=512 << 20)),
        (3, _line('[2BYTEASR_PROGRESS]', percent=50, downloaded=256 << 20, total=512 << 20, speed=50 << 20,
                  phase='download')),
    ])
    assert activity.task_title() == '模型 1/2 · 下载 model.safetensors'
    assert activity.weights_line() == '全部模型 512.0 MiB / 2.00 GiB（25%）'
    assert activity.step_fraction['weights'] == 0.25
    assert activity.events[0].text == '需要下载 2 个模型，约 2.00 GiB'
    assert '沿用已校验的文件 1 个（256.0 MiB），不重新下载' in [event.text for event in activity.events]
    activity.feed(_line('[2BYTEASR_PROGRESS]', percent=100, downloaded=512 << 20, total=512 << 20, speed=0,
                        phase='verify'), 4.0, 0)
    assert activity.step_fraction['weights'] == 0.375
    activity.feed('[下载] Qwen/Qwen3-ASR-1.7B @ 7278e1e7', 5.0, 0)
    assert activity.task_title() == '模型 2/2 · 下载 Qwen/Qwen3-ASR-1.7B'
    assert activity.step_fraction['weights'] == 0.375  # the next model starts at zero, the step does not


def test_slow_source_is_named_with_its_speed():
    lines = [(second, _line('[2BYTEASR_RUNTIME_DOWNLOAD]', file='torch.whl', package='torch', index=1, count=1,
                            downloaded=second * (100 << 10), total=2 << 30, speed=100 << 10, source='PyTorch 官方',
                            host='download.pytorch.org', phase='download')) for second in range(1, 41)]
    activity = _run(lines)
    slow = activity.assess(40.5, running=True)
    assert (slow.level, slow.headline) == ('slow', '下载速度很慢（100 KB/s）')
    assert slow.where.startswith('当前：运行环境 · 下载 PyTorch（1/1）')  # slow is not stuck
    assert slow.why.startswith('PyTorch 官方 目前只有这个速度，按这个速度还要约 5 小时')


def test_tool_download_bytes_come_from_the_supervisor_heartbeat():
    activity = _run([
        (0, _line('[2BYTEASR_PHASE]', phase='tools_preparing')),
        (0, '[工具] 来源 1/7：GitHub 官方'),
        (0, _line('[2BYTEASR_DEPLOY]', phase='tools_preparing', state='start', component='uv')),
        (15, _line('[2BYTEASR_DEPLOY]', phase='tools_preparing', state='waiting', component='uv', downloaded=4 << 20,
                   progress_age_s=2, waiting='subprocess')),
    ])
    assert activity.task.kind == 'tool' and activity.task.done == 4 << 20
    assert activity.last_bytes_at == 13
    assert activity.source_line() == '来源：GitHub 官方  ·  第 1/7 个来源'
    assert activity.figures(15).startswith('已下载 4.0 MiB')


def test_waiting_for_another_preparation_is_explained():
    activity = _run([(0, _line('[2BYTEASR_PHASE]', phase='waiting_for_lock'))])
    waiting = activity.assess(10, running=True)
    assert (waiting.level, waiting.headline) == ('waiting', '正在等待另一项环境准备')
    assert '最多等待 60 秒' in waiting.why


def test_weights_suggestions_follow_the_current_host():
    activity = _run([(0, '[下载] x/y @ 1'),
                     (0, _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', label='ModelScope', host='modelscope.cn',
                               attempt=1, total=3, status='trying'))])
    assert activity.suggest_source('AUTO') == 'HF_MIRROR'
    activity.task.host = 'hf-mirror.com'
    assert activity.suggest_source('HF_MIRROR') == 'MODELSCOPE'
    assert activity.suggest_source('HF_MIRROR', modelscope_ok=False) == 'HF_OFFICIAL'
    assert host_region('mirror.sjtu.edu.cn') == 'domestic' and host_region('files.pythonhosted.org') == 'foreign'


def test_process_tree_probe_sees_cpu_and_disk_writes_of_children(tmp_path):
    target = tmp_path / 'blob.bin'
    code = ("import time,os\n"
            "end=time.time()+3\n"
            "with open(r'%s','wb') as f:\n"
            "    while time.time()<end:\n"
            "        f.write(os.urandom(1<<20)); f.flush(); os.fsync(f.fileno())\n" % target)
    # A wrapper parent: the work happens in a grandchild, like PowerShell -> python -> uv.
    process = subprocess.Popen([sys.executable, '-c', f'import subprocess,sys;subprocess.run([sys.executable,"-c",{code!r}])'])
    try:
        probe = ProcessTreeProbe()
        time.sleep(0.8)
        assert probe.sample(process.pid, time.monotonic())['warmup']
        time.sleep(1.0)
        sample = probe.sample(process.pid, time.monotonic())
        assert sample['processes'] >= 2
        assert sample['cpu'] > 5 and sample['io'] > 1 << 20
    finally:
        process.wait(15)
    assert ProcessTreeProbe().sample(process.pid, time.monotonic()) is None


def test_mfa_runtime_lines_become_steps_progress_and_events():
    # The user's MFA download (2026-10-21) showed only a looping bar: its runtime
    # is installed by scripts/install_mfa_runtime.py with plain [运行库] lines.
    activity = _run([
        (0, _line('[2BYTEASR_PHASE]', phase='preparing')),
        (0, '[运行库] 正在准备 MFA（实验）运行环境'),
        (1, _line('[2BYTEASR_PHASE]', phase='runtime_installing')),
        (1, '[运行库] 获取 micromamba 2.3.2：https://conda.anaconda.org/conda-forge/win-64/micromamba-2.3.2-0.tar.bz2'),
        (4, '[运行库] 下载 MFA 运行环境的 221 个包（约 340 MB）'),
        (9, '[运行库] 下载失败，换下一个来源：https://mirrors.ustc.edu.cn/anaconda/cloud/conda-forge/win-64/x.conda（URLError: timed out）'),
        (10, '[运行库] MFA 运行环境：40/221 个包，85 MB（来源：mirrors.tuna.tsinghua.edu.cn）'),
        (12, '[运行库] MFA 运行环境：60/221 个包，120 MB（来源：mirrors.tuna.tsinghua.edu.cn）'),
    ])
    assert _states(activity, 12) == ['done', 'active', 'pending', 'pending']  # never shown under 准备工具
    assert activity.task_title() == '下载 MFA 运行环境（221 个包）'
    assert round(activity.task_fraction(), 3) == round(60 / 221, 3)
    assert activity.figures(12).startswith('已下载 60/221 个包（120.0 MiB，共约 340.0 MiB）')
    assert activity.source_line() == '来源：mirrors.tuna.tsinghua.edu.cn'
    assert 'mirrors.ustc.edu.cn 没有成功，换下一个来源' in [event.text for event in activity.events]
    assert activity.last_line.startswith('[运行库] MFA 运行环境：60/221 个包')
    for second, line in ((40, '[运行库] 正在组装 MFA 运行环境（不再联网）'), (90, '[运行库] 安装 MFA 中文分词依赖'),
                         (95, '[运行库] 下载中文分词模型 postag（约 39 MB）'),
                         (120, '[运行库] 检查 MFA 运行环境能否运行（首次可能要一两分钟）'),
                         (200, '[运行库] MFA 运行环境就绪：C:\\Users\\x\\runtimes\\mfa（MFA 3.3.9，196 秒）'),
                         (200, _line('[2BYTEASR_PHASE]', phase='runtime_ready'))):
        activity.feed(line, float(second), 1_800_000_000.0 + second)
        if second == 40:
            assert activity.task_title() == '组装 MFA 运行环境（不联网）' and activity.task_fraction() is None
        if second == 95:
            assert activity.task_title() == '下载中文分词模型 postag（约 39.0 MiB）'
    assert activity.step_state['runtime'] == 'done'
    texts = [event.text for event in activity.events]
    assert 'MFA 运行环境的包已下载' in texts and 'MFA 运行环境就绪（MFA 3.3.9）' in texts


def test_a_silent_mfa_download_with_an_idle_tree_offers_a_domestic_source():
    activity = _run([(0, '[运行库] 正在准备 MFA（实验）运行环境'),
                     (1, '[运行库] 下载 MFA 运行环境的 221 个包（约 340 MB）'),
                     (5, '[运行库] MFA 运行环境：10/221 个包，12 MB（来源：conda.anaconda.org）')])
    for second in range(100, 200):
        activity.tick(float(second), {'cpu': 0.2, 'io': 0})
    stuck = activity.assess(200, running=True, mode='AUTO', modelscope_ok=False)
    assert stuck.level == 'stalled'
    assert stuck.where.startswith('卡在：运行环境 · 下载 MFA 运行环境（221 个包）')
    assert 'conda.anaconda.org' in stuck.why and '国内来源' in stuck.why
    assert stuck.actions == ('switch:HF_MIRROR', 'export')  # MFA models are not on ModelScope


def test_newest_output_line_hides_paths():
    from twobyteasr.local_models.download_activity import display_line
    assert display_line('[运行库] 清理 C:\\Users\\me\\AppData\\x 完成') == '[运行库] 清理 … 完成'
    assert display_line('a  b\tc') == 'a b c'
    assert len(display_line('x' * 500)) == 180


def test_painted_widgets_follow_the_interface_zoom():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from twobyteasr.local_models.download_widgets import ActivityGraph, StepTrack, WrapRow
    QApplication.instance() or QApplication([])
    track, graph = StepTrack(), ActivityGraph()
    base_track, base_graph = track.height(), graph.height()
    track.apply_ui_zoom(1.75)
    graph.apply_ui_zoom(1.75)
    assert track.minimumHeight() == round(base_track * 1.75) and graph.minimumHeight() == round(base_graph * 1.75)
    assert track.property('uiZoomOwnSize') and graph.property('uiZoomOwnSize')
    row = WrapRow(spacing=8)
    row.setSpacing(14)  # what ui_zoom does to every layout
    assert row._gap == 14


def test_steady_tool_download_reported_every_15_seconds_is_not_slow():
    # 2026-10-22 real run (mainland line): uv from the Aliyun mirror at a steady
    # ~325 KB/s, reported by the supervisor every 15 s, flipped to "速度较慢".
    start = '[2BYTEASR_DEPLOY] ' + json.dumps({'component': 'uv', 'state': 'start', 'phase': 'tools_preparing',
                                               'arguments': ['https://mirrors.aliyun.com/pypi/packages/uv.whl']})
    lines = [(0, '[2BYTEASR_PHASE] {"phase":"tools_preparing"}'), (0, '[工具] 来源 1/7：阿里云 PyPI 镜像'), (0, start)]
    for index, downloaded in enumerate((4984832, 9879552, 14643200, 19460096, 23957504), 1):
        lines.append((15 * index, _line('[2BYTEASR_DEPLOY]', waiting='subprocess', state='waiting', downloaded=downloaded,
                                        elapsed_s=15 * index, phase='tools_preparing', component='uv', progress_age_s=0)))
    activity = DownloadActivity({})
    activity.reset(0.0, 1_800_000_000.0)
    levels = set()
    for second in range(1, 79):
        for at, line in lines:
            if at == second - 1:
                activity.feed(line, float(at), 1_800_000_000.0 + at)
        levels.add(activity.assess(second, running=True).level)
    assert levels <= {'ok'}, levels


def test_failure_that_another_source_cannot_fix_offers_no_source_switch():
    # 2026-10-22 real run: all 104 packages were installed, then the bundled
    # FireRed source was missing. The notice offered "改用 ModelScope 继续".
    activity = _run([(0, '[2BYTEASR_PHASE] {"phase":"dependencies_installing"}'),
                     (1, 'Installed 104 packages in 6.79s'),
                     (2, 'Traceback (most recent call last):'),
                     (2, ' + accelerate==1.12.0'),
                     (2, "    raise RuntimeError('安装包缺少已锁定 FireRed 源码；不需要系统 Git')"),
                     (2, 'RuntimeError: 安装包缺少已锁定 FireRed 源码；不需要系统 Git'),
                     (3, '[2BYTEASR_INSTALL_ERROR] {"phase":"dependencies_installing","message":"子程序退出码 1"}')])
    activity.mark_finished('failed', 4)
    failure = ('首次选择的字幕识别组合 · 运行环境准备阶段（尚未开始下载权重）\n依赖安装失败：子程序退出码 1，阶段 dependencies_installing\n'
               '已校验的文件会保留。请展开日志查看该阶段的具体错误后重试。')
    failed = activity.assess(5, running=False, mode='AUTO', failure=failure)
    assert failed.actions == ('export',)
    assert failed.why.endswith('子程序报错：安装包缺少已锁定 FireRed 源码；不需要系统 Git')
    timeout = activity.assess(5, running=False, mode='AUTO', failure='运行环境来源连接或传输超时。已校验的文件会保留。')
    assert timeout.actions == ('switch:MODELSCOPE', 'export')


def test_second_environment_does_not_show_the_first_ones_package_counts():
    # 2026-10-22 real run: "创建 moss 运行环境" showed main's "依赖已下载，正在解压安装 · 共 104 个依赖".
    deploy = lambda **payload: _line('[2BYTEASR_DEPLOY]', **payload)
    activity = _run([(0, deploy(phase='environment_building', state='start', component='main')),
                     (1, deploy(phase='dependencies_installing', state='start', component='创建运行环境')),
                     (2, deploy(phase='dependencies_installing', state='start', component='下载并安装依赖')),
                     (3, 'Resolved 104 packages in 3.73s'), (30, 'Prepared 104 packages in 24.21s'),
                     (40, 'Installed 104 packages in 9.22s'),
                     (50, deploy(phase='environment_building', state='start', component='moss')),
                     (52, deploy(phase='dependencies_installing', state='start', component='创建运行环境'))])
    assert activity.task_title() == '创建 moss 运行环境'
    assert '104' not in activity.figures(53)


def test_slow_github_word_segmentation_model_is_slow_not_stuck():
    # 2026-10-22 real run (mainland line): spacy_ontonotes (32 MB) from GitHub at
    # ~55 KB/s, no output and almost no disk writes, became "可能卡住" after 150 s.
    lines = [(0, '[运行库] 正在准备 MFA（实验）运行环境'), (1, '[运行库] 下载中文分词模型 spacy_ontonotes（约 32 MB）')]
    for second in range(3, 200, 5):
        mb = (second - 1) * 55 / 1024
        lines.append((second, f'[运行库] 中文分词模型 spacy_ontonotes：{mb:.1f}/32.0 MB（来源：github.com）'))
    activity = DownloadActivity({})
    activity.reset(0.0, 1_800_000_000.0)
    levels = {}
    for second in range(1, 200):
        for at, line in lines:
            if at == second - 1:
                activity.feed(line, float(at), 1_800_000_000.0 + at)
        levels.setdefault(activity.assess(second, running=True, modelscope_ok=False).level, second)
    assert 'quiet' not in levels and 'stalled' not in levels, levels
    assert levels.get('slow', 999) <= 40, levels
    slow = activity.assess(199, running=True, modelscope_ok=False)
    assert slow.where.startswith('当前：运行环境 · 下载中文分词模型 spacy_ontonotes')
    assert '自动试用其他来源' in slow.why and '已下载的部分会保留' in slow.why  # PkusegDownload, 2026-10-22
    assert slow.actions == ('switch:HF_MIRROR', 'export')
    assert '剩余约' in activity.figures(199) and activity.task_fraction() is not None
    stopped = activity.assess(199 + 61, running=True, modelscope_ok=False)
    assert stopped.level == 'stalled'  # a real stall is still reported


def test_word_segmentation_source_changes_show_in_recent_activity():
    # install_mfa_runtime.PkusegDownload (2026-10-22): GitHub at ~50 KB/s, a trial
    # of ghfast.top takes over from the same offset; later trials are not faster.
    p = '[运行库] 中文分词模型 postag：'
    activity = _run([
        (0, '[运行库] 下载中文分词模型 postag（约 39 MB）'),
        (14, p + '0.6/39.5 MB（来源：github.com）'),
        (22, p + 'github.com 最近 30 秒平均 48 KB/s，试用 ghfast.top'),
    ])
    assert activity.events[-1].text == 'github.com 只有 48 KB/s，试用 ghfast.top'
    # A trial reads for a few seconds without progress lines: not "no new data".
    assert activity.assess(36, running=True, modelscope_ok=False).level not in {'quiet', 'stalled'}
    for second, line in ((30, p + 'github.com（48 KB/s）太慢，已改用 ghfast.top（333 KB/s），从 1.0 MB 处继续'),
                         (30, p + '1.0/39.5 MB（来源：ghfast.top）'), (32, p + '1.7/39.5 MB（来源：ghfast.top）'),
                         (52, p + 'ghfast.top 最近 30 秒平均 330 KB/s，试用 ghproxy.net'),
                         (60, p + 'ghproxy.net 试下 24 KB/s，不比 ghfast.top 明显更快，继续使用 ghfast.top'),
                         (100, p + 'ghfast.top 最近 30 秒平均 335 KB/s，试用 gh-proxy.org'),
                         (108, p + 'gh-proxy.org 没有成功（HTTP 403），继续使用 ghfast.top'),
                         (108, p + '其他来源都不比 ghfast.top 明显更快，继续使用它')):
        activity.feed(line, float(second), 1_800_000_000.0 + second)
        if second == 30 and 'MB（来源' in line:
            assert activity.current_rate(31) == 333 * 1024  # the trial's speed until the new source has its own
    rows = [(event.text, event.tone) for event in activity.events]
    assert rows == [('github.com 只有 48 KB/s，已改用 ghfast.top（333 KB/s），从 1.0 MiB 处继续', 'warn'),
                    ('ghproxy.net 试下 24 KB/s，不比 ghfast.top 明显更快，继续使用 ghfast.top', ''),
                    ('gh-proxy.org 没有成功，继续使用 ghfast.top', 'warn'),
                    ('其他来源都不比 ghfast.top 明显更快，继续使用它', '')]
    assert activity.source_line() == '来源：ghfast.top'
    more = _run([(0, p + 'ghfast.top 从 12.3 MB 处继续'),
                 (1, p + 'ghproxy.net 不支持断点续传，从头下载（已下载的 12.3 MB 先保留）'),
                 (2, p + 'ghproxy.net 连接中断（timed out），重新连接'),
                 (3, p + 'github.com（20 KB/s）太慢，已改用 ghproxy.net（900 KB/s），从头下载（它不支持断点续传，已下载的 2.0 MB 先保留）')])
    assert [event.text for event in more.events] == [
        '从 ghfast.top 的 12.3 MiB 处继续下载', 'ghproxy.net 不支持断点续传，从头下载（已下载的 12.3 MiB 先保留）',
        'ghproxy.net 连接中断，重新连接', 'github.com 只有 20 KB/s，已改用 ghproxy.net（900 KB/s）；它不支持断点续传，从头下载']


def test_no_switch_offer_once_every_source_of_the_model_failed():
    # 2026-10-22 real run: MFA models are only on Hugging Face; huggingface.co and
    # hf-mirror.com both failed, yet the notice still offered 改用 Hugging Face 官方.
    source = lambda mode, label, host, attempt, status: _line(
        '[2BYTEASR_SOURCE]', mode=mode, label=label, host=host, attempt=attempt, total=2, status=status)
    activity = _run([
        (0, '[下载] MontrealCorpusTools/mandarin_mfa @ cfbee140'),
        (0, source('HF_OFFICIAL', 'Hugging Face 官方', 'huggingface.co', 1, 'trying')),
        (1, _line('[2BYTEASR_FILE]', file='acoustic/final.mdl', index=2, total=12, phase='downloading')),
        (30, source('HF_OFFICIAL', 'Hugging Face 官方', 'huggingface.co', 1, 'failed')),
        (30, source('HF_MIRROR', 'HF 镜像', 'hf-mirror.com', 2, 'trying')),
        (31, _line('[2BYTEASR_FILE]', file='acoustic/final.mdl', index=2, total=12, phase='downloading')),
        (70, source('HF_MIRROR', 'HF 镜像', 'hf-mirror.com', 2, 'failed')),
    ])
    stuck = activity.assess(140, running=True, mode='AUTO', modelscope_ok=False)
    assert stuck.level == 'stalled'
    assert stuck.actions == ('export',)
    assert '都试过了' in stuck.why and 'HTTPS_PROXY' in stuck.why
    # One failed source still leaves the other to offer.
    fresh = _run([(0, '[下载] x/y @ 1'), (0, source('HF_OFFICIAL', 'Hugging Face 官方', 'huggingface.co', 1, 'trying')),
                  (1, _line('[2BYTEASR_FILE]', file='a.bin', index=1, total=1, phase='downloading'))])
    assert fresh.suggest_source('AUTO', modelscope_ok=False) == 'HF_MIRROR'
    fresh.feed(source('HF_OFFICIAL', 'Hugging Face 官方', 'huggingface.co', 1, 'failed'), 2.0, 0)
    assert fresh.suggest_source('AUTO', modelscope_ok=False) == 'HF_MIRROR'
    fresh.feed(source('HF_MIRROR', 'HF 镜像', 'hf-mirror.com', 2, 'failed'), 3.0, 0)
    assert fresh.suggest_source('AUTO', modelscope_ok=False) == ''


def test_a_retry_of_the_same_file_keeps_the_no_data_clock():
    activity = _run([(0, '[下载] x/y @ 1'),
                     (0, _line('[2BYTEASR_FILE]', file='model.bin', index=1, total=1, phase='downloading')),
                     (25, '[重试] 来源暂时没有响应'),
                     (25, _line('[2BYTEASR_FILE]', file='model.bin', index=1, total=1, phase='downloading'))])
    # 0 bytes for 30 s across the retry: still waiting for a reply, not 正常进行.
    assert activity.assess(30, running=True).level == 'quiet'


def test_all_model_bytes_present_reads_100_percent():
    activity = _run([(0, '- 需下载 1 个模型：x'), (0, '- 预计下载约 1.00 GiB；建议至少保留 2.0 GiB 可用空间。'),
                     (1, '[下载] x/y @ 1'),
                     (1, _line('[2BYTEASR_CACHE]', file='a.bin', bytes=(1 << 30) - (1 << 20), origin='verified staging'))])
    assert activity.weights_line().endswith('（100%）')
