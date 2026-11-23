"""What 兔白 can look up herself before she answers (2026-11-14).

User (2026-11-14): when someone asks “why so many errors after recognition”, 兔白 should go
and look at what went wrong, like an MCP tool would, instead of guessing. The AI asks for a
lookup with ``"check": "last_task"`` in its JSON answer; the chat runs it here and asks the AI
again with the result.

``last_task_summary`` reads the newest recognition report (the same reports 「识别记录」
lists), runs the local diagnosis the history page uses (``run_diagnosis``) and returns a short
plain-text summary: the media name, status, models, counts and the top findings with their
cause and advice. Paths, keys and subtitle text are never included. No Qt; nothing is sent.
"""
from __future__ import annotations

import sys
from pathlib import Path, PureWindowsPath

CHECKS = ('last_task', 'hardware')        # (extended below with the step-2 reads)
MAX_FINDINGS = 3
_LIMIT = 160


def _short(text, limit: int = _LIMIT) -> str:
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def report_roots() -> list[Path]:
    from ..recognition import reporting
    from ..recognition.task_journal import task_root
    roots = [task_root(), Path(reporting.REPORT_ROOT)]
    for extra in getattr(reporting, 'LEGACY_REPORT_ROOTS', ()) or ():
        if Path(extra) not in roots:
            roots.append(Path(extra))
    return roots


def newest_report(roots=None):
    """(path) of the most recently written report, or None."""
    from ..recognition.recognition_history import list_report_files
    listing, _errors = list_report_files(report_roots() if roots is None else roots)
    if not listing:
        return None
    return max(listing, key=lambda row: row[1])[0]


def _finding_lines(record, ai_ready) -> list[str]:
    from ..recognition.run_diagnosis import DiagnosisInput, diagnose_run
    try:
        diagnosis = diagnose_run(DiagnosisInput(report=record.payload, ai_ready=ai_ready))
    except Exception:  # noqa: BLE001 - a report the checks cannot read still has its facts
        return []
    lines = []
    for finding in diagnosis.findings[:MAX_FINDINGS]:
        issue = finding.issue
        # Finding-specific text can interpolate a path, raw exception or cue.
        # Only the application's fixed diagnosis catalogue crosses this boundary.
        parts = [f'【{issue.severity}】{issue.title}']
        if issue.cause:
            parts.append(f'原因：{_short(issue.cause)}')
        if issue.advice:
            parts.append(f'怎么办：{_short(issue.advice)}')
        lines.append(' / '.join(parts))
    return lines


def last_task_summary(*, ai_ready: bool | None = None, roots=None) -> str:
    """The newest recognition task in a few plain lines, for 兔白 to read."""
    from ..recognition.recognition_history import parse_recognition_report
    path = newest_report(roots)
    if path is None:
        return '还没有任何识别记录（小兔纸可能还没做过字幕，或者记录在别的电脑上）。'
    try:
        record = parse_recognition_report(path)
    except Exception:  # raw parser errors can contain private paths
        return '最近一次识别的记录读不出来，请在本机「识别记录」查看详情。'
    lines = [f'素材：{_short(PureWindowsPath(record.media_name).name, 60)}',
             f'状态：{record.status_label or record.status}（{record.completed_at or "时间未记录"}）']
    models = [f'{name}：{value}' for name, value in (('主力转写', record.primary_model), ('字幕时间轴', record.timeline_model),
                                                     ('文字复核', record.review_model), ('文字 AI', record.ai_model)) if value]
    if models:
        lines.append('用的模型：' + '；'.join(models))
    lines.append(f'字幕 {record.cue_count} 条；待复核 {record.review_count} 项；警告或错误 {record.anomaly_count} 项；'
                 f'用了 {record.glossary_count} 个词库')
    if record.problems or record.review_notes:
        lines.append(f'记录中有 {len(record.problems)} 条问题提示、{len(record.review_notes)} 条复核说明；'
                     '原始内容仅在本机「识别记录」中查看。')
    findings = _finding_lines(record, ai_ready)
    if findings:
        lines.append('本机诊断（和「识别记录」里「排查原因」同一套）：')
        lines += [f'- {line}' for line in findings]
    else:
        lines.append('本机诊断没有发现已知问题。')
    return '\n'.join(lines)


def _cpu_name() -> str:
    import platform
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                return ' '.join(str(winreg.QueryValueEx(key, 'ProcessorNameString')[0]).split())
        except OSError:
            pass
    return platform.processor() or platform.machine()


def _gb(value) -> str:
    return f'{float(value) / 1024 ** 3:.1f} GB'


def hardware_summary(settings: dict | None = None) -> str:
    """This computer in a few lines (2026-11-14, user: 兔白 should look, not ask “do you have an NVIDIA card?”).

    The same reads the app already makes: ``vram_check.read_gpu_inventory`` (nvidia-smi, cached),
    the OS memory counters, the CPU name, free disk space where models go, and whether the chosen
    recognition setup needs an NVIDIA card (``hardware.selected_cuda_components``). Up to 8 s on
    a machine where nvidia-smi hangs, so it runs off the GUI thread with the chat's AI request.
    """
    import os
    import platform
    import shutil
    release = platform.release()
    build = platform.version().split('.')[-1]
    if sys.platform == 'win32' and release == '10' and build.isdigit() and int(build) >= 22000:
        release = '11'                     # Windows 11 still reports itself as 10
    lines = [f'系统：{platform.system()} {release}（{platform.machine()}）']
    try:
        from ..system.vram_check import read_gpu_inventory
        gpu = read_gpu_inventory()
        if gpu.status == 'nvidia':
            name = gpu.name if gpu.name.upper().startswith('NVIDIA') else f'NVIDIA {gpu.name}'
            lines.append(f'显卡：{name}，显存 {gpu.total_gb:.1f} GB')
        elif gpu.status == 'no_nvidia':
            lines.append('显卡：没有找到可用的 NVIDIA 显卡（需要 NVIDIA 显卡的本机模型不能用）')
        elif gpu.status == 'not_applicable':
            lines.append('显卡：Mac 的 Apple 芯片（显存和内存共用）')
        else:
            lines.append('显卡：有 NVIDIA 工具但读不到显卡信息')
    except Exception:  # noqa: BLE001
        lines.append('显卡：读取失败')
    lines.append(f'处理器：{_short(_cpu_name(), 80)}，{os.cpu_count() or "?"} 个线程')
    try:
        from ..system.memory_budget import memory_status
        memory = memory_status()
        lines.append(f'内存：共 {_gb(memory["total"])}，现在空闲 {_gb(memory["available"])}')
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..runtime_paths import detect_install_root
        free = shutil.disk_usage(detect_install_root()).free
        lines.append(f'软件所在磁盘剩余：{_gb(free)}（本机模型默认下载到这里）')
    except Exception:  # noqa: BLE001
        pass
    if settings:
        try:
            from ..system.hardware import selected_cuda_components
            needs = selected_cuda_components(settings)
            lines.append('现在的识别方案：' + ('需要 NVIDIA 显卡（' + '、'.join(needs[:4]) + '）' if needs
                                             else '不需要 NVIDIA 显卡'))
        except Exception:  # noqa: BLE001
            pass
    return '\n'.join(lines)


# ---------------------------------------------------------------- 2026-11-15, agent step 2
# User (2026-11-15): she should pull the software's own diagnostics and information herself and
# work out what went wrong. These read only, off the GUI thread, and pass the same boundaries as
# the rest of this module: no keys, no full paths, no raw tracebacks; the diagnostic summary is
# the redacted one 「回报问题／导出诊断」 writes (paths become aliases there).

def recent_tasks_summary(*, limit: int = 8, roots=None) -> str:
    """The last few recognition tasks, one line each (newest first)."""
    from ..recognition.recognition_history import list_report_files, parse_recognition_report
    listing, _errors = list_report_files(report_roots() if roots is None else roots)
    if not listing:
        return '还没有任何识别记录。'
    rows = []
    for number, (path, _stamp, *_rest) in enumerate(sorted(listing, key=lambda row: row[1], reverse=True)[:limit], 1):
        try:
            record = parse_recognition_report(path)
        except Exception:  # noqa: BLE001 - unreadable reports are counted, never quoted
            rows.append(f'{number}. （一条记录读不出来）')
            continue
        rows.append(f'{number}. {record.completed_at or "时间未记录"} · {_short(PureWindowsPath(record.media_name).name, 40)} · '
                    f'{record.status_label or record.status} · 字幕 {record.cue_count} 条 · 待复核 {record.review_count} · '
                    f'警告或错误 {record.anomaly_count} · 主力 {record.primary_model or "?"}')
    return f'最近 {len(rows)} 次识别（新的在上；要打开哪次的结果，用 open_result 填这个编号）：\n' + '\n'.join(rows)


DIAGNOSTIC_LIMIT = 3600


def diagnostics_summary(*, deadline_s: float = 20.0) -> str:
    """The redacted diagnostic summary 「回报问题／导出诊断」 starts with: conclusion, then the steps with issues."""
    import time
    from ..diagnostics import editor_diagnostics
    from ..diagnostics.support_bundle import collect, summary
    from ..diagnostics.support_triage import analyze
    instance = editor_diagnostics._INSTANCE
    root = instance.root if instance is not None else editor_diagnostics.root_dir()
    try:
        data = collect(root, instance=instance, scope='recent', deadline=time.monotonic() + deadline_s)
        data['analysis'] = analyze(data, None)
        text = summary(data, 'bunny', '', None)
    except Exception as exc:  # noqa: BLE001 - a missing record is said, not raised
        return f'诊断记录读不出来（{type(exc).__name__}）。可以请小兔纸用「回报问题／导出诊断…」导出给作者。'
    text = '\n'.join(line for line in str(text).splitlines() if not line.startswith(('用户描述', '2ByteASR 诊断摘要')))
    return text if len(text) <= DIAGNOSTIC_LIMIT else text[:DIAGNOSTIC_LIMIT - 1] + '…（后面省略）'


_SECRET_WORDS = ('key', 'token', 'secret', 'password', 'cookie', 'authorization')


def settings_summary(settings: dict | None) -> str:
    """The recognition and AI choices, never a key (2026-11-15)."""
    if not isinstance(settings, dict):
        return '读不到设置。'
    models = settings.get('models') or {}
    switches = settings.get('switches') or {}

    def visible(name, value):
        return (not any(word in str(name).casefold() for word in _SECRET_WORDS)
                and isinstance(value, (str, int, float, bool)) and str(value) != '')
    pick = ('primary_asr_backend', 'firered_asr_backend', 'qwen_asr_backend', 'speaker_source', 'timeline_backend',
            'polish_provider', 'polish_model', 'group_provider', 'group_model', 'translation_target', 'source_language',
            'polish_enable_thinking', 'group_enable_thinking')
    rows = [f'{name}={models[name]}' for name in pick if name in models and visible(name, models[name])]
    on = [name for name, value in switches.items() if value is True and visible(name, value)]
    off = [name for name, value in switches.items() if value is False and visible(name, value)]
    text = '模型与服务：' + ('；'.join(rows) or '（默认）')
    text += '\n打开的开关：' + ('、'.join(sorted(on)) or '无') + '\n关闭的开关：' + ('、'.join(sorted(off)) or '无')
    return text


def models_summary(settings: dict | None = None) -> str:
    """Which local models are on this computer and in what state (no paths)."""
    try:
        from ..local_models.model_registry import scan_model_registry
        registry = scan_model_registry()
    except Exception as exc:  # noqa: BLE001
        return f'读不到模型清单（{type(exc).__name__}）。'
    words = {'PARTIAL': '没下载完', 'CORRUPT': '文件坏了', 'INCOMPATIBLE': '这台电脑不能用', 'UNREADABLE': '读不到'}
    good, other = [], []
    for model_id, record in sorted(registry.records.items()):
        health = str(getattr(record.health, 'value', record.health)).upper()
        if model_id in registry.installed_keys():
            good.append(model_id)
        elif health in words:
            missing = f'，缺 {len(record.missing_files)} 个文件' if record.missing_files else ''
            other.append(f'{model_id}（{words[health]}{missing}）')
    lines = ['已装好的本机模型：' + ('、'.join(good) or '没有')]
    if other:
        lines.append('装了但不完整或读不到的：' + '、'.join(other[:12]))
    if getattr(registry, 'pending_keys', None):
        lines.append('正在下载或处理：' + '、'.join(sorted(registry.pending_keys)))
    return '\n'.join(lines)


def export_roots() -> list[Path]:
    import os
    from ..projects.studio_project import studio_data_root
    return [Path(os.environ.get('TWOBYTEASR_EXPORT_LOG_ROOT') or studio_data_root() / 'logs' / 'exports')]


def exports_summary(limit: int = 3) -> str:
    """The newest video exports from their run logs (2026-11-22): when, how it ended, at which stage
    and why, the encoder and the length asked for. 兔白 had nothing to read when an export failed or
    stopped moving; recognition had ``last_task``. Never a path, never subtitle text."""
    import json
    import time
    manifests = []
    for root in export_roots():
        if root.is_dir():
            manifests += [path for path in root.glob('*/*/manifest.json') if path.is_file()]
    manifests.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if not manifests:
        return '没有找到视频导出的记录（这台电脑上还没导出过视频，或记录已清理）。'
    rows = []
    for index, path in enumerate(manifests[:limit], 1):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        when = time.strftime('%m-%d %H:%M', time.localtime(path.stat().st_mtime))
        settings = data.get('settings') if isinstance(data.get('settings'), dict) else {}
        failure = data.get('failure') if isinstance(data.get('failure'), dict) else None
        if failure:
            from ..exports.studio_render import STAGE_LABELS
            stage = STAGE_LABELS.get(failure.get('stage'), str(failure.get('stage') or '?'))
            message = str(failure.get('message') or failure.get('reason') or '').split('\n\n', 1)[0]
            ended = f'失败，停在「{stage}」：{_short(message, 140)}'
        elif data.get('published'):
            ended = '成功'
        else:
            ended = '没有结束记录（还在导出，或中途被关掉 / 卡住后关掉）'
        encoder = (data.get('last_encoding') or {}).get('actual_encoder') or settings.get('encoder') or '?'
        asked = data.get('requested_settings') if isinstance(data.get('requested_settings'), dict) else {}
        size = f"{settings.get('width') or '?'}×{settings.get('height') or '?'}"
        rows.append(f'{index}. {when}：{ended}；编码器 {encoder}，{settings.get("container") or "?"}，{size}，'
                    f'请求的编码器 {asked.get("encoder") or data.get("requested_encoder") or "?"}')
    return '\n'.join(rows) or '视频导出的记录读不出来。'


CHECKS = ('last_task', 'hardware', 'history', 'diagnostics', 'settings', 'models', 'exports')


def run_check(name: str, *, ai_ready: bool | None = None, settings: dict | None = None) -> str:
    if name == 'last_task':
        return last_task_summary(ai_ready=ai_ready)
    if name == 'hardware':
        return hardware_summary(settings)
    if name == 'history':
        return recent_tasks_summary()
    if name == 'diagnostics':
        return diagnostics_summary()
    if name == 'settings':
        return settings_summary(settings)
    if name == 'models':
        return models_summary(settings)
    if name == 'exports':
        return exports_summary()
    return ''


__all__ = ['CHECKS', 'diagnostics_summary', 'hardware_summary', 'last_task_summary', 'models_summary', 'newest_report',
           'recent_tasks_summary', 'report_roots', 'run_check', 'settings_summary']
