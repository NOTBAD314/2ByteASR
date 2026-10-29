"""macOS eligibility and safe host diagnostics. Never import native AI backends.

Eligibility is not model readiness: the existing isolated worker still has to
load the selected backend and perform its real sample before registration.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

MINIMUM_MACOS = '14.0'
ARCHITECTURES = ('arm64',)
FEATURE_MINIMUMS = {'app': MINIMUM_MACOS, 'main': '14.0', 'moss': '14.0', 'mlx': '14.0'}


def parse_macos_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', value):
        raise ValueError('Invalid macOS version: ' + repr(value))
    parts = tuple(int(p) for p in value.split('.'))
    return parts + (0,) * (3 - len(parts))


def normalized_architecture(value: str) -> str:
    return {'aarch64':'arm64','amd64':'x86_64','x64':'x86_64'}.get(value.lower(), value.lower())


def compatibility_problem(feature: str = 'app', *, system=None, machine=None, release=None) -> str:
    system = sys.platform if system is None else system
    machine = normalized_architecture(platform.machine() if machine is None else machine)
    release = platform.mac_ver()[0] if release is None else release
    if system != 'darwin':
        return '此运行环境需要 Apple Silicon 原生 arm64 macOS。'
    if machine not in ARCHITECTURES:
        return '此安装包需要 Apple 芯片（Apple Silicon）原生 arm64；Intel 与 Rosetta 进程不适用，请使用原生 Mac 入口。'
    minimum = FEATURE_MINIMUMS[feature]
    try:
        if parse_macos_version(release) < parse_macos_version(minimum):
            return f'此组件需要 macOS {minimum} 或更新版本；当前为 {release}。没有开始下载。'
    except ValueError:
        return '无法确认 macOS 完整版本，已停止准备；请提供系统诊断记录。'
    return ''


def require_compatible(feature='app', **host) -> None:
    problem = compatibility_problem(feature, **host)
    if problem:
        raise RuntimeError(problem)


def host_diagnostics() -> dict:
    """Only system/build facts, no serial number, environment dump or API keys."""
    machine = normalized_architecture(platform.machine())
    result = dict(platform=sys.platform, macos=platform.mac_ver()[0], process_architecture=machine,
                  hardware_architecture=machine, rosetta=None, python=platform.python_version(),
                  package_architectures=list(ARCHITECTURES), minimum_macos=MINIMUM_MACOS)
    if sys.platform == 'darwin':
        for name, field in (('sysctl.proc_translated','rosetta'), ('hw.optional.arm64','hardware_arm64')):
            try:
                probe = subprocess.run(['/usr/sbin/sysctl','-in',name], capture_output=True, text=True, timeout=3)
                if probe.returncode == 0 and probe.stdout.strip() in ('0','1'):
                    result[field] = probe.stdout.strip() == '1'
            except (OSError, subprocess.TimeoutExpired):
                pass
        if result.get('hardware_arm64') or machine == 'arm64':
            result['hardware_architecture'] = 'arm64'
        if machine == 'arm64':
            result['rosetta'] = False
    result['packages'] = {}
    for name in ('PySide6','shiboken6','av','numpy','mlx','mlx-metal','mlx-audio','torch','onnxruntime'):
        try:
            result['packages'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result['packages'][name] = None
    return result


def write_startup_diagnostics(root: Path, destination: Path, *, stage: str, error: str = '') -> None:
    payload = host_diagnostics()
    payload.update(stage=stage, error=error)
    for name in ('2byteasr_version.json','2byteasr_build.json'):
        try:
            data = json.loads((root/name).read_text('utf-8-sig'))
            payload[name] = {k:data[k] for k in ('version','app_version','git_sha','git_dirty','build_channel','source_sha256') if k in data}
        except (OSError, ValueError):
            pass
    try:
        build = json.loads((root/'native-build-inputs.json').read_text('utf8'))
        payload['build_host_macos'] = build.get('macos')
        payload['bundled_tool_versions'] = {name:value.get('version') for name,value in build.get('native_tools',{}).items()}
        payload['build_python_packages'] = build.get('resolved_python_packages',[])
    except (OSError,ValueError,AttributeError):
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def failure_category(error: str) -> str:
    text = error.lower()
    for category, markers in (
        ('architecture',('incompatible architecture','bad cpu type','rosetta','原生 arm64','missing_architecture')),
        ('missing_library',('library not loaded','image not found','no module named','cannot load library')),
        ('missing_symbol',('symbol not found','undefined symbol')),
        ('signature_or_notarization',('code signature','notariz','gatekeeper','quarantine')),
        ('minimum_system',('requires macos','built for macos','需要 macos','无法确认 macos','deployment target','minimum_macos')),
        ('backend_initialization',('metal','mps','mlx'))):
        if any(marker in text for marker in markers):return category
    return 'python_startup'
