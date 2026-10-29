"""Real-window look of the redesigned model download window (2026-10-21).

Started by ``scripts/verify_download_window_headed.py`` inside the real app on a
private desktop with isolated data. Nothing is downloaded: each window is driven
with installer output lines in the format of the real first-deployment runs
(2026-10-20/21) and synthetic process-tree samples, so every state can be shown
on purpose — PyTorch download, dependency install, weights, a slow source, a
stuck dependency install, a long model load, failure and success, and the MFA
(experimental) runtime and model load — in the themes named by
``TWOBYTEASR_DOWNLOAD_WINDOW_THEMES``, at a narrow size and at 120% / 175%
interface zoom (2026-10-21: the user runs mixed-DPI monitors at 120%). Two
real child processes replay a whole run through the window's own pipe, clock
and process probe. Writes ``<theme>-<state>.png`` and ``result.json``.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

COMBO = ('moss', 'firered_aed', 'qwen_asr')


def _line(prefix, **payload):
    return f'{prefix} {json.dumps(payload, ensure_ascii=False)}'


def _deploy(**payload):
    return _line('[2BYTEASR_DEPLOY]', **payload)


def _phase(phase, **payload):
    return _line('[2BYTEASR_PHASE]', phase=phase, **payload)


def _torch(t, done, rate, source, host, **extra):
    return t, _line('[2BYTEASR_RUNTIME_DOWNLOAD]', file='torch-2.11.0+cu128-cp310-cp310-win_amd64.whl', package='torch',
                    index=1, count=2, downloaded=int(done), total=2753152602, speed=float(rate), source=source, host=host,
                    phase='download', **extra)


def _tools_and_python():
    return [
        (0, _phase('preparing')), (0, _phase('runtime_installing')), (0, _phase('waiting_for_lock')),
        (0, _phase('tools_preparing')),
        (0, '[工具] 获取固定版本 uv 0.11.7，每个来源都校验 SHA-256'),
        (0, '[工具] 来源 1/7：阿里云 PyPI 镜像'),
        (0, _deploy(phase='tools_preparing', state='start', component='uv')),
        (5, _line('[2BYTEASR_TOOL_HTTP]', http_status='200', downloaded=25447744, redirects=0, elapsed_s=4.7)),
        (5, '[工具] 已从 阿里云 PyPI 镜像 取得 uv，SHA-256 校验通过'),
        (6, _deploy(phase='tools_preparing', state='done', exit_code=0)),
        (6, _phase('interpreter_preparing')),
        (7, 'Downloading cpython-3.10.19-windows-x86_64-none (download) (21.5MiB)'),
        (40, ' Downloaded cpython-3.10.19-windows-x86_64-none (download)'),
        (40, 'Installed Python 3.10.19 in 33.10s'),
        (41, _phase('dependencies_installing')),
        (42, _deploy(phase='environment_building', state='start', component='main', reason='missing_or_invalid')),
    ]


def _torch_lines(until=150, rate=12 << 20):
    lines = _tools_and_python() + [
        (43, '[PyTorch] 从 PyTorch 官方 下载 torch-2.11.0+cu128-cp310-cp310-win_amd64.whl（2.56 GiB）')]
    lines += [_torch(t, (t - 43) * 420_000, 420_000, 'PyTorch 官方', 'download.pytorch.org') for t in range(44, 62, 3)]
    lines += [(62, '[PyTorch] PyTorch 官方 最近 30 秒只有 0.4 MB/s，试用 上海交大 PyTorch 镜像')]
    offset = 18 * 420_000
    event = dict(kind='switched', **{'from': 'PyTorch 官方'}, to='上海交大 PyTorch 镜像', from_rate=391182.2,
                 to_rate=7657472.0, offset=offset)
    lines += [_torch(t, offset + (t - 64) * rate, rate * (0.85 + 0.3 * ((t * 7) % 10) / 10), '上海交大 PyTorch 镜像',
                     'mirror.sjtu.edu.cn', event=event) for t in range(64, until + 1)]
    return lines


_PACKAGES = [('scipy', '39.3MiB'), ('dynet38', '1.2MiB'), ('sentencepiece', '1.2MiB'), ('nagisa', '20.4MiB'),
             ('numba', '2.7MiB'), ('av', '26.8MiB'), ('pydantic-core', '1.9MiB'), ('sympy', '6.0MiB'),
             ('pillow', '6.9MiB'), ('networkx', '1.6MiB'), ('llvmlite', '39.9MiB'), ('pandas', '10.8MiB'),
             ('gradio', '30.8MiB'), ('scikit-learn', '8.5MiB'), ('tokenizers', '2.6MiB'), ('transformers', '11.4MiB'),
             ('numpy', '12.3MiB'), ('cython', '2.7MiB')]


def _packages_lines(source='阿里云 PyPI 镜像', index='1/5', downloaded=11, start=210):
    lines = _torch_lines(200, 60 << 20) + [
        (201, '[PyTorch] torch-2.11.0+cu128-cp310-cp310-win_amd64.whl 下载完成，SHA-256 与锁定值一致'),
        (202, _line('[2BYTEASR_RUNTIME_DOWNLOAD]', package='torchaudio', index=2, count=2, downloaded=1671568,
                    total=1671568, phase='done', source='上海交大 PyTorch 镜像', host='mirror.sjtu.edu.cn')),
        (203, _deploy(phase='dependencies_installing', state='start', component='main', attempt=1, source=source,
                      reason='固定依赖清单')),
        (203, f'[运行库] {source}（{index}）；固定版本与 SHA-256 校验；只允许已声明的纯 Python 源码包构建'),
        (204, _deploy(phase='dependencies_installing', state='start', component='下载并安装依赖')),
        (208, 'Resolved 104 packages in 5.08s'),
    ]
    lines += [(start + index // 3, f'Downloading {name} ({size})') for index, (name, size) in enumerate(_PACKAGES)]
    lines += [(start + 8 + index, f' Downloaded {name}') for index, (name, _size) in enumerate(_PACKAGES[:downloaded])]
    return lines


def _weights_lines():
    lines = _packages_lines(downloaded=len(_PACKAGES)) + [
        (240, 'Prepared 104 packages in 34.54s'), (254, 'Installed 104 packages in 14.29s'),
        (255, _deploy(phase='environment_checking', state='start', component='检查依赖')),
        (255, 'Checked 104 packages in 3ms'),
        (270, _phase('runtime_ready')),
        (271, '- 需下载 3 个模型：moss、firered_aed、qwen_asr'),
        (271, '- 预计下载约 8.24 GiB；建议至少保留 8.7 GiB 可用空间。'),
        (272, '[下载] OpenMOSS-Team/MOSS-Transcribe-Diarize @ e6d68cdfcddbdad1a7e8454f0cb859cad76e2502'),
        (272, _phase('weights_downloading')),
        (272, _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', label='ModelScope', host='modelscope.cn', attempt=1, total=3,
                    status='trying')),
        (272, _line('[2BYTEASR_CACHE]', file='tokenizer.json', bytes=11423222, origin='verified staging')),
        (273, _line('[2BYTEASR_FILE]', file='model-00000-of-00001.safetensors', index=17, total=17, phase='downloading')),
        (273, _line('[2BYTEASR_FILE]', file='model-00000-of-00001.safetensors', size=1817113576)),
    ]
    lines += [(t, _line('[2BYTEASR_PROGRESS]', percent=0, downloaded=(t - 273) * 90_000_000, total=1817113576,
                        speed=90_000_000, phase='download')) for t in range(274, 293)]
    lines += [
        (294, _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', host='modelscope.cn', label='ModelScope',
                    url='https://modelscope.cn/api', attempt=1, total=1, status='selected')),
        (300, _phase('weights_ready', source='MODELSCOPE')),
        (301, '[下载] Qwen/Qwen3-ASR-1.7B @ 7278e1e70fe206f11671096ffdd38061171dd6e5'),
        (301, _line('[2BYTEASR_SOURCE]', mode='MODELSCOPE', label='ModelScope', host='modelscope.cn', attempt=1, total=3,
                    status='trying')),
        (302, _line('[2BYTEASR_FILE]', file='model-00001-of-00002.safetensors', index=3, total=10, phase='downloading')),
        (302, _line('[2BYTEASR_FILE]', file='model-00001-of-00002.safetensors', size=4220320824)),
    ]
    lines += [(t, _line('[2BYTEASR_PROGRESS]', percent=0, downloaded=(t - 302) * 94_000_000, total=4220320824,
                        speed=94_000_000 * (0.9 + 0.2 * ((t * 3) % 7) / 7), phase='download')) for t in range(303, 330)]
    return lines


def _heartbeats(begin, end, phase, component):
    return [(t, _deploy(phase=phase, state='waiting', component=component, elapsed_s=t - begin, output_age_s=t - begin,
                        waiting='subprocess')) for t in range(begin + 15, end, 15)]


MFA = ('mfa_aligner',)
MFA_NAME = 'Montreal Forced Aligner（实验）'


def _mfa_runtime_lines(until=300):
    lines = [(0, _phase('preparing')), (0, '[模型工坊] 只处理：mfa_aligner、mfa_aligner_ja'),
             (0, '[运行库] 正在准备 MFA（实验）运行环境'), (1, _phase('runtime_installing')),
             (1, '[运行库] 获取 micromamba 2.3.2：https://conda.anaconda.org/conda-forge/win-64/micromamba-2.3.2-0.tar.bz2'),
             (6, '[运行库] 下载 MFA 运行环境的 221 个包（约 340 MB）'),
             (16, '[运行库] 下载失败，换下一个来源：https://conda.anaconda.org/conda-forge/win-64/'
                  'kaldi-5.5.1112-cpu_h8f0e7f0_6.conda（TimeoutError: timed out）')]
    for t in range(8, min(until, 108), 2):
        done = min(221, (t - 6) * 221 // 100)
        lines.append((t, f'[运行库] MFA 运行环境：{done}/221 个包，{done * 340 // 221} MB（来源：'
                         f'{"conda.anaconda.org" if t < 20 else "mirrors.tuna.tsinghua.edu.cn"}）'))
    lines += [(t, line) for t, line in (
        (110, '[运行库] 正在组装 MFA 运行环境（不再联网）'), (160, '[运行库] 安装 MFA 中文分词依赖'),
        (170, '[运行库] 下载中文分词模型 spacy_ontonotes（约 32 MB）'), (176, '[运行库] 下载中文分词模型 postag（约 39 MB）'),
        (182, '[运行库] 检查 MFA 运行环境能否运行（首次可能要一两分钟）'),
        (236, '[运行库] MFA 运行环境就绪：C:\\Users\\x\\AppData\\Local\\2ByteASR\\runtimes\\mfa（MFA 3.3.9，230 秒）'),
        (236, _phase('runtime_ready'))) if t <= until]
    return lines


def _mfa_full_lines():
    lines = _mfa_runtime_lines() + [
        (237, '2ByteASR 模型下载'), (237, '- 需下载 2 个模型：mfa_aligner、mfa_aligner_ja'),
        (237, '- 预计下载约 0.26 GiB；建议至少保留 2.0 GiB 可用空间。')]
    t = 238
    for repo, size in (('MontrealCorpusTools/mandarin_mfa', 144863556), ('MontrealCorpusTools/japanese_mfa', 138656473)):
        lines += [(t, f'[下载] {repo} @ cfbee14002d514fcf411c16676877a96b7afe6ff'), (t, _phase('weights_downloading')),
                  (t, _line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co',
                            attempt=1, total=1, status='trying')),
                  (t + 1, _line('[2BYTEASR_FILE]', file='acoustic/final.mdl', index=2, total=12, phase='downloading')),
                  (t + 1, _line('[2BYTEASR_FILE]', file='final.mdl', size=size))]
        lines += [(t + 1 + k, _line('[2BYTEASR_PROGRESS]', percent=0, downloaded=min(size, k * 12_000_000), total=size,
                                    speed=12_000_000, phase='download')) for k in range(1, 13)]
        lines += [(t + 14, _line('[2BYTEASR_SOURCE]', mode='HF_OFFICIAL', label='Hugging Face 官方', host='huggingface.co',
                                 url='https://huggingface.co/x', attempt=1, total=1, status='selected')),
                  (t + 15, _phase('weights_ready', source='HF_OFFICIAL'))]
        t += 16
    lines += [(t, _deploy(phase='model_loading', state='start', component='mfa_aligner')),
              (t + 2, _phase('model_loading', model='mfa_aligner')),
              (t + 2, '[2BYTEASR_MFA] loading acoustic model mandarin_mfa')]
    lines += _heartbeats(t, t + 100, 'model_loading', 'mfa_aligner')
    return lines, t


SCENARIOS = {
    # name: (lines, duration, sample(t) -> dict, expected notice tone or None)
    'pytorch': (lambda: _torch_lines(150), 150, lambda t: dict(cpu=9 + (t % 5), io=12e6 if t > 64 else 4e5), None),
    'packages': (lambda: _packages_lines(), 222, lambda t: dict(cpu=22 + (t % 7), io=30e6), None),
    'weights': (lambda: _weights_lines(), 330, lambda t: dict(cpu=14, io=90e6), None),
    'stalled': (lambda: _packages_lines(source='PyPI 官方', index='1/5', downloaded=4, start=210)
                + _heartbeats(222, 420, 'dependencies_installing', '下载并安装依赖'),
                420, lambda t: dict(cpu=0.4, io=1200), 'bad'),
    'slow': (lambda: _torch_lines(64) + [
        _torch(t, 18 * 420_000 + (t - 64) * 120_000, 120_000, 'PyTorch 官方', 'download.pytorch.org')
        for t in range(64, 130, 2)], 130, lambda t: dict(cpu=2, io=120_000), 'warn'),
    'loading': (lambda: _weights_lines() + [
        (331, _phase('weights_ready', source='MODELSCOPE')),
        (340, _deploy(phase='model_loading', state='start', component='moss')),
        (342, _phase('model_loading', model='moss'))] + _heartbeats(340, 720, 'model_loading', 'moss'),
        720, lambda t: dict(cpu=96 + (t % 9), io=8e6), 'info'),
    'mfa-packages': (lambda: _mfa_runtime_lines(70), 70, lambda t: dict(cpu=12, io=4e6), None),
    # The user's 2026-10-21 screenshot: weights verified, the model loading, nothing visible moving.
    'mfa-loading': (lambda: _mfa_full_lines()[0], _mfa_full_lines()[1] + 80, lambda t: dict(cpu=88, io=3e6), None),
}
SCENARIO_MODELS = {'mfa-packages': (MFA, MFA_NAME), 'mfa-loading': (MFA, MFA_NAME)}
ZOOM_SCENARIOS = ('pytorch', 'stalled', 'mfa-loading')


def start(output: Path):
    from PySide6.QtCore import QProcess, QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..local_models.model_workshop import MODELS, ModelDownloadDialog
    output.mkdir(parents=True, exist_ok=True)
    themes = [item for item in os.environ.get('TWOBYTEASR_DOWNLOAD_WINDOW_THEMES', 'grape,warm').split(',') if item]
    result = dict(checks=[], identity=load_build_identity().to_dict(), themes=themes, shots=[], passed=False)
    app = QApplication.instance()
    window = next((widget for widget in app.topLevelWidgets() if type(widget).__name__ == 'MainWindow'), None)

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=200):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def make_dialog(keys=COMBO, name='首次选择的字幕识别组合'):
        model = next(item for item in MODELS if item.download_key == keys[0])
        parent = window.workshop_page if window is not None and hasattr(window, 'workshop_page') else window
        dialog = ModelDownloadDialog(Path(os.environ['TWOBYTEASR_INVOKER_ROOT']), model, parent,
                                     download_keys=keys, display_name=name)
        dialog._activity_timer.stop()  # the audit owns the clock
        return dialog

    def as_running(dialog, duration):
        now, wall = time.monotonic(), time.time()
        begin = now - duration
        dialog.process.state = lambda: QProcess.ProcessState.Running
        dialog.process.processId = lambda: 0
        dialog._started_at = begin
        dialog._activity.reset(begin, wall - duration)
        dialog.source_combo.setEnabled(False)
        dialog.start_button.setEnabled(False)
        dialog.start_button.setText('正在下载…')
        dialog.rebuild_runtime_button.setVisible(False)
        dialog.pause_button.setVisible(True)
        return begin, wall - duration

    def play(dialog, lines, duration, sample):
        begin, wall = as_running(dialog, duration)
        events = sorted(lines, key=lambda item: item[0])
        index = 0
        for second in range(0, duration + 1):
            while index < len(events) and events[index][0] <= second:
                line = events[index][1]
                dialog._activity.feed(line, begin + events[index][0], wall + events[index][0])
                dialog._handle_progress_line(line)
                if not line.startswith('[2BYTEASR_RUNTIME_DOWNLOAD] '):
                    dialog.log.appendPlainText(line)  # as _read_output does
                index += 1
            dialog._activity.tick(begin + second, sample(second))
        dialog._refresh_view(time.monotonic())

    def layout_checks(dialog, label):
        rect = dialog.rect()
        body = dialog.body_scroll.widget()
        buttons = [button for button in dialog.findChildren(QPushButton) if button.isVisible()]
        # Inside the scrolling body a button below the fold is reachable; the
        # header and footer must fit, and a notice must be in view (next check).
        outside = [button.text() for button in buttons if not body.isAncestorOf(button)
                   and (not rect.contains(button.mapTo(dialog, button.rect().bottomRight()))
                        or not rect.contains(button.mapTo(dialog, button.rect().topLeft())))]
        check(f'{label}: every visible button outside the scrolling body lies inside the window', not outside, outside)
        if dialog.notice.isVisible():
            viewport = dialog.body_scroll.viewport()
            parts = [dialog.notice_title] + [dialog.notice_buttons.itemAt(index).widget()
                                             for index in range(dialog.notice_buttons.count())]
            hidden = [getattr(part, 'text', lambda: '')()[:30] for part in parts if part is not None
                      and not (viewport.rect().contains(part.mapTo(viewport, part.rect().topLeft()))
                               and viewport.rect().contains(part.mapTo(viewport, part.rect().bottomRight())))]
            check(f'{label}: the notice title and its buttons are in view without scrolling', not hidden, hidden)
        footer = [dialog.start_button, dialog.close_button, dialog.pause_button, dialog.rebuild_runtime_button,
                  dialog.check_download_button, dialog.copy_diagnostic_button, dialog.export_diagnostic_button]
        footer = [button for button in footer if button.isVisible()]
        overlaps = [(a.text(), b.text()) for i, a in enumerate(footer) for b in footer[i + 1:]
                    if a.geometry().translated(a.mapTo(dialog, a.rect().topLeft()) - a.geometry().topLeft()).intersects(
                        b.geometry().translated(b.mapTo(dialog, b.rect().topLeft()) - b.geometry().topLeft()))]
        check(f'{label}: footer buttons do not overlap', not overlaps, overlaps)
        body = dialog.body_scroll.widget()
        check(f'{label}: body fits the width (no clipped column)',
              body.minimumSizeHint().width() <= dialog.body_scroll.viewport().width() + 1,
              dict(body=body.minimumSizeHint().width(), viewport=dialog.body_scroll.viewport().width()))
        cut = [button.text() for button in buttons if button.width() < button.sizeHint().width() - 2]
        check(f'{label}: button labels are not squeezed', not cut, cut)
        from PySide6.QtWidgets import QLabel
        clipped = [item.text()[:40] for item in dialog.findChildren(QLabel)
                   if item.isVisible() and item.wordWrap() and item.text()
                   and item.height() < item.heightForWidth(item.width()) - 2]
        check(f'{label}: wrapped texts get their full height', not clipped, clipped)

    def shoot(dialog, name):
        path = output / f'{name}.png'
        dialog.grab().save(str(path))
        result['shots'].append(path.name)

    def live_replay(tag='live-replay', lines=None, keys=COMBO, name='首次选择的字幕识别组合', busy_from=340):
        """The real path: a child process prints the lines, the window's own clock and probe run."""
        import sys
        from ..local_models.download_activity import ProcessTreeProbe
        lines = lines or (_weights_lines() + [(331, _phase('weights_ready')), (340, _phase('model_loading', model='moss')),
                                              (360, _phase('ready', model='moss')),
                                              (361, _phase('completed', inference_success=True))])
        feed_path = output / f'{tag}-lines.json'
        feed_path.write_text(json.dumps(sorted(lines, key=lambda item: item[0]), ensure_ascii=False), 'utf-8')
        script = output / 'live_replay_child.py'
        script.write_text(
            'import json, os, sys, time\n'
            'lines = json.load(open(sys.argv[1], encoding="utf-8"))\n'
            'last = 0\n'
            'for second, line in lines:\n'
            '    time.sleep(max(0.0, (second - last) * 0.03))\n'
            '    last = second\n'
            f'    if second >= {busy_from}:\n'
            '        end = time.time() + 1.2\n'  # a busy silent step: CPU work and disk writes
            '        with open(sys.argv[2], "wb") as stream:\n'
            '            while time.time() < end:\n'
            '                stream.write(os.urandom(1 << 18)); stream.flush()\n'
            '    print(line, flush=True)\n', 'utf-8')
        dialog = make_dialog(keys, name)
        dialog.resize(800, 720)
        dialog.show()
        settle(150)
        dialog._activity_timer.start(1000)
        now = time.monotonic()
        dialog._started_at = now
        dialog._activity.reset(now, time.time())
        dialog._probe = ProcessTreeProbe()
        dialog.process.setWorkingDirectory(str(output))
        dialog.process.start(sys.executable, ['-u', str(script), str(feed_path), str(output / f'{tag}-blob.bin')])
        seen = dict(steps=set(), probe=0, pills=set(), shot=False, output=set())
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            settle(200)
            seen['steps'].add(dialog._activity.step)
            seen['pills'].add(dialog.health_pill.text())
            latest = dialog._activity.latest_activity()
            if latest is not None:
                seen['probe'] += 1
            if dialog.task_output.isVisible():
                seen['output'].add(dialog._activity.task.kind)
            want = 'runtime' if keys == MFA else 'weights'
            if not seen['shot'] and dialog._activity.step == want and dialog._activity.task.done > 0:
                shoot(dialog, f'{tag}-running-immediate')
                settle(350)  # one more round of layout: a clipped label here would be a real bug
                shoot(dialog, f'{tag}-running')
                figures = dialog.task_figures
                check(f'{tag}: figures are not clipped while text changes',
                      figures.height() >= figures.heightForWidth(figures.width()) - 1,
                      dict(height=figures.height(), needed=figures.heightForWidth(figures.width())))
                seen['shot'] = True
            if dialog.process.state() == QProcess.ProcessState.NotRunning and dialog._finished_ok:
                break
        settle(400)
        shoot(dialog, f'{tag}-done')
        expected = {'runtime', 'weights', 'verify'} if keys == MFA else {'tools', 'runtime', 'weights', 'verify'}
        check(f'{tag}: real child output reaches every step', expected <= seen['steps'],
              sorted(item for item in seen['steps'] if item))
        check(f'{tag}: the process-tree probe sampled the real child', seen['probe'] > 0, seen['probe'])
        check(f'{tag}: graph received values', len(dialog._activity.graph()[0]) > 3, len(dialog._activity.graph()[0]))
        check(f'{tag}: newest output shown without the raw log', bool(seen['output']) and not dialog.log.isVisible(),
              sorted(seen['output']))
        check(f'{tag}: finished as done with every step complete', dialog._finished_ok
              and all(row[2] == 'done' for row in dialog.step_track.rows()) and dialog.health_pill.text() == '已完成',
              dict(ok=dialog._finished_ok, pill=dialog.health_pill.text(), steps=[row[2] for row in dialog.step_track.rows()]))
        check(f'{tag}: no false stall while it ran', not ({'可能卡住', '等待回应'} & seen['pills']), sorted(seen['pills']))
        result[tag] = dict(steps=sorted(item for item in seen['steps'] if item), probe_samples=seen['probe'],
                           pills=sorted(seen['pills']), output_kinds=sorted(seen['output']))
        dialog._activity_timer.stop()
        dialog.close()
        dialog.deleteLater()
        settle(100)

    def zoom_pass():
        """120% and 175% interface zoom (Ctrl+wheel); in memory only, QSettings are isolated anyway."""
        from ..app import ui_zoom
        try:
            for percent in (120, 175):
                ui_zoom._state.update(percent=percent, touched=True)
                for theme in themes:
                    apply_theme(theme)
                    settle(200)
                    for name in ZOOM_SCENARIOS:
                        lines, duration, sample, _tone = SCENARIOS[name]
                        dialog = make_dialog(*SCENARIO_MODELS.get(name, (COMBO, '首次选择的字幕识别组合')))
                        dialog.resize(800, 720)
                        dialog.show()
                        ui_zoom.apply_to(dialog)
                        settle(200)
                        play(dialog, lines(), duration, sample)
                        settle(300)
                        label = f'{theme}-{name}-zoom{percent}'
                        shoot(dialog, label)
                        expected = round((6 + 44) * percent / 100)
                        check(f'{label}: step track and graph follow the zoom',
                              abs(dialog.step_track.height() - expected) <= 1
                              and abs(dialog.activity_graph.height() - round(30 * percent / 100)) <= 1,
                              dict(track=dialog.step_track.height(), expected=expected, graph=dialog.activity_graph.height()))
                        layout_checks(dialog, label)
                        dialog.process.state = lambda: QProcess.ProcessState.NotRunning
                        dialog.close()
                        dialog.deleteLater()
                        settle(100)
        finally:
            ui_zoom._state.update(percent=100)
            for theme in themes[:1]:
                apply_theme(theme)

    def run():
        try:
            for theme in themes:
                apply_theme(theme)
                settle(300)
                for name, (lines, duration, sample, tone) in SCENARIOS.items():
                    dialog = make_dialog(*SCENARIO_MODELS.get(name, (COMBO, '首次选择的字幕识别组合')))
                    dialog.resize(800, 720)
                    dialog.show()
                    settle(150)
                    play(dialog, lines(), duration, sample)
                    settle(250)
                    label = f'{theme}-{name}'
                    shoot(dialog, label)
                    if name == 'mfa-loading':
                        check(f'{label}: the MFA load says it is still working, with the newest output',
                              dialog.health_pill.text() == '仍在工作' and dialog.task_output.isVisible()
                              and dialog.step_track.rows()[3][2] == 'active',
                              dict(pill=dialog.health_pill.text(), output=dialog.task_output.text(),
                                   title=dialog.task_title.text()))
                    if name == 'mfa-packages':
                        check(f'{label}: MFA packages are measured progress under 运行环境',
                              dialog.task_bar.isVisible() and dialog.step_track.rows()[1][2] == 'active'
                              and '个包' in dialog.task_figures.text(),
                              dict(figures=dialog.task_figures.text(), steps=[row[2] for row in dialog.step_track.rows()]))
                    shown = dialog.notice.isVisible()
                    check(f'{label}: notice {"shown (" + tone + ")" if tone else "hidden"}',
                          shown == bool(tone) and (not tone or dialog.notice.property('tone') == tone),
                          dict(shown=shown, tone=dialog.notice.property('tone'), pill=dialog.health_pill.text(),
                               title=dialog.notice_title.text()))
                    check(f'{label}: no busy animation (legacy bar hidden)', not dialog.progress.isVisible())
                    layout_checks(dialog, label)
                    if name == 'stalled':
                        dialog.resize(480, 640)
                        settle(250)
                        shoot(dialog, f'{label}-narrow')
                        layout_checks(dialog, f'{label}-narrow')
                    dialog.process.state = lambda: QProcess.ProcessState.NotRunning
                    dialog.close()
                    dialog.deleteLater()
                    settle(100)
                # failure and success through the real result handler
                for name, code, closing in (('failed', 1, [
                        (512, _deploy(phase='model_loading', state='start', component='firered_aed')),
                        (513, _phase('model_loading', model='firered_aed')),
                        (520, '[2BYTEASR_INSTALL_ERROR] ' + json.dumps(dict(
                            phase='model_loading', category='model_load_failed',
                            message='FIRERED worker failed (exit 1): train_bpe1000.model 找不到'), ensure_ascii=False))]),
                        ('done', 0, [(512, _phase('model_loading', model='qwen_asr')),
                                     (560, _phase('ready', model='qwen_asr')),
                                     (561, _phase('completed', inference_success=True))])):
                    dialog = make_dialog()
                    dialog.resize(800, 720)
                    dialog.show()
                    settle(150)
                    play(dialog, _weights_lines() + [(331, _phase('weights_ready'))] + closing, 562,
                         lambda t: dict(cpu=40, io=5e6))
                    dialog.process.state = lambda: QProcess.ProcessState.NotRunning
                    dialog._finished_v2(code, None)
                    settle(300)
                    label = f'{theme}-{name}'
                    shoot(dialog, label)
                    if name == 'failed':
                        check(f'{label}: failure notice names the step', dialog.notice.isVisible()
                              and dialog.notice_title.text() == '没有完成：加载试跑', dialog.notice_title.text())
                    else:
                        check(f'{label}: success shows all steps done and no notice',
                              not dialog.notice.isVisible() and all(row[2] == 'done' for row in dialog.step_track.rows()))
                    layout_checks(dialog, label)
                    dialog.close()
                    dialog.deleteLater()
                    settle(100)
            zoom_pass()
            live_replay()
            mfa_lines, mfa_load = _mfa_full_lines()
            mfa_lines = [item for item in mfa_lines if '"waiting"' not in item[1]] + [
                (mfa_load + 20, _phase('ready', model='mfa_aligner')),
                (mfa_load + 21, _phase('completed', inference_success=True))]
            live_replay('mfa-live-replay', mfa_lines, MFA, MFA_NAME, busy_from=mfa_load)
            result['passed'] = all(item['passed'] for item in result['checks'])
        except Exception:  # noqa: BLE001
            result['error'] = traceback.format_exc()
        finally:
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
            QTimer.singleShot(200, app.quit)

    QTimer.singleShot(500, run)
