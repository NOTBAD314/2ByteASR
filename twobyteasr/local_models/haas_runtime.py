"""Prepare the pinned Windows CrispASR components without changing other runtimes."""
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from ..recognition.haas_backend import RUNTIME_REVISION, RUNTIME_VERSION, runtime_environment, runtime_executable
from ..runtime_paths import get_runtime_paths
from ..system.runtime_package_download import WheelDownload

SOURCE = f'https://github.com/CrispStrobe/CrispASR/releases/download/v{RUNTIME_VERSION}'
ARCHIVES = {
    'cpu': ('crispasr-windows-x86_64-cpu.zip',
            'f3b9643b7874e66cd366cda81d37d101677f18ab6e3a3255ff65dae19a439740'),
    'cuda': ('crispasr-windows-x86_64-cuda13.zip',
             '55110590ae8d32a973ad04b7096884f3eb958e73aa6171ad14481c31c3549c92'),
}
BUNDLED_CPU_FILES = {
    'crispasr.exe': 'd7e1109e956e98bbcc82eef6edbe27715b839a84cd6d83855ab294e4c803ca6c',
    'openblas.dll': 'b134a7311569aa049a407a7bbaa0e70ec5c5f1c8067924a501baed2b58608c2a',
    'LICENSE': '51b246c135c42131ec3bee3ed9a70284b2559f0516d76c9f617dcddb9e682869',
    'THIRD_PARTY_NOTICES.txt': '7ad088611f61730ea5bcd495db8ed74f3fb77d68653238f3197b480f04b20010',
}
CRT_WHEEL = 'shiboken6-6.9.2-cp39-abi3-win_amd64.whl'
CRT_WHEEL_SHA256 = '68c33d565cd4732be762d19ff67dfc53763256bac413d392aa8598b524980bc4'
CRT_FILES = {
    'msvcp140.dll': '5bc530e0f09b3f023cd81f28e9ae406f304f93ffcb81bde0656017fc2cf8ae7e',
    'vcomp140.dll': 'b7985a04701831e7a6b8f440428c8b55dcd696d97ccd298681a991c6e1adc858',
    'vcruntime140.dll': 'bbea6c008604b7d4a24f59ca093dfddf37be085759c0f5a46a8bbe6c3c0e173b',
    'vcruntime140_1.dll': '677c07f1f00b697e82986ff393305126c0ddee184712487945d80cd35b0f0823',
}


def cpu_runtime_directory(root):
    return Path(root) / 'tools' / 'crispasr' / RUNTIME_VERSION / 'cpu'


def verify_bundled_cpu(root):
    from ..model_integrity import sha256_file
    folder = cpu_runtime_directory(root)
    for name, expected in {**BUNDLED_CPU_FILES, **CRT_FILES}.items():
        path = folder / name
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f'請準備固定版 CrispASR Windows CPU 元件：{path}')
    return folder


def prepare_bundled_cpu(root):
    """Stage the independently verified Microsoft DLLs alongside the external EXE."""
    from ..model_integrity import sha256_file

    root = Path(root)
    folder = cpu_runtime_directory(root)
    if any(not (folder / name).is_file() for name in CRT_FILES):
        wheel = root / 'wheels' / CRT_WHEEL
        if not wheel.is_file() or sha256_file(wheel) != CRT_WHEEL_SHA256:
            raise RuntimeError(f'請準備固定版建置所需的 Qt wheel：{wheel}')
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel) as archive:
            for name in CRT_FILES:
                target = folder / name
                if not target.is_file():
                    target.write_bytes(archive.read('shiboken6/' + name))
    return verify_bundled_cpu(root)


def _version(executable, device):
    if executable is None:
        return False
    try:
        run = subprocess.run([os.fspath(executable), '--version'], capture_output=True, timeout=15,
                             env=runtime_environment(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = run.stdout + run.stderr
    return (run.returncode == 0 and RUNTIME_VERSION.encode() in output and RUNTIME_REVISION.encode() in output
            and (device != 'cuda' or b'cpu,cuda' in output))


def prepare(device):
    import sys
    if sys.platform != 'win32':
        raise RuntimeError('目前固定的 Haas 執行元件僅提供 Windows x64。')
    found = runtime_executable(device)
    if _version(found, device):
        return found
    paths = get_runtime_paths()
    base = paths.managed_runtime_root / 'crispasr' / RUNTIME_VERSION
    base.mkdir(parents=True, exist_ok=True)
    filename, expected = ARCHIVES[device]
    download = WheelDownload(base / 'downloads', filename, [expected],
                             [dict(label='CrispASR GitHub', url=SOURCE, official=True)],
                             family='CrispASR')
    download.fetch()
    target = base / device
    with tempfile.TemporaryDirectory(dir=base, prefix=f'.{device}-') as temporary:
        stage = Path(temporary) / 'runtime'
        stage.mkdir()
        with zipfile.ZipFile(download.target) as package:
            entries = [item for item in package.infolist() if not item.is_dir()]
            for member in entries:
                name = Path(member.filename).name
                if name in {'crispasr.exe', 'LICENSE', 'THIRD_PARTY_NOTICES.txt'} or name.endswith('.dll'):
                    with package.open(member) as origin, (stage / name).open('xb') as output:
                        shutil.copyfileobj(origin, output)
        if (not _version(stage / 'crispasr.exe', device)
                or not all((stage / name).is_file() for name in ('LICENSE', 'THIRD_PARTY_NOTICES.txt'))):
            raise RuntimeError('正式 CrispASR 發行檔未包含有效執行檔或授權文件。')
        if target.exists():
            if _version(target / 'crispasr.exe', device):
                return target / 'crispasr.exe'
            backup = Path(temporary) / 'previous'
            target.rename(backup)
            try:
                stage.rename(target)
            except OSError:
                backup.rename(target)
                raise
            return target / 'crispasr.exe'
        try:
            stage.rename(target)
        except FileExistsError:
            if not _version(target / 'crispasr.exe', device):
                raise
    return target / 'crispasr.exe'
