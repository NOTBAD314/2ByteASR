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
CUDA_FILES = {
    'crispasr.dll': 'a5f03bb8580915f9a4ff6be4e047e149b145cf81cd9935485797c16579029f30',
    'crispasr.exe': '627dbf650b34912d5abb2c7221c33d8281a6cdbefcfc7b2bc083b03fbd6d9286',
    'cublas64_13.dll': '5d083083cdd613577496791dd96d00fe3a78c955684b53ca46a8ffa3e0b1e170',
    'cublasLt64_13.dll': 'e1c26671801ecd435baf97c6e9cfe28196cf55005c2039356b48030b09ce5dd5',
    'cudart64_13.dll': '58c509047f9dd1879cf82c6d5375a95c02c7bd295ae6c8362c745c936e2afc31',
    'ggml-base.dll': '5d5d788ee117c891ec71b5af52fde108b9f86d7898b379000f2e2e6bb3dc5ec3',
    'ggml-cpu.dll': 'b97b9f76e86873ceb2467dae666bcfd32ea4087db7b4c23be6e3ead9b4dd8e41',
    'ggml-cuda.dll': '714fdb75deb45f562eca38b165b0b8ca270705819298b2c9d629de73624b3651',
    'ggml.dll': 'ea23ff7f5b32084d9f4ea860e5e8cacb2c72a5a509853d7e4612ddb08a3b420e',
    'LICENSE': BUNDLED_CPU_FILES['LICENSE'],
    'THIRD_PARTY_NOTICES.txt': BUNDLED_CPU_FILES['THIRD_PARTY_NOTICES.txt'],
}
ARCHIVE_BYTES = {'cpu': 9_702_256, 'cuda': 570_614_503}
RUNTIME_BYTES = {'cpu': 23_248_000, 'cuda': 727_400_000}
CRT_WHEEL = 'shiboken6-6.9.2-cp39-abi3-win_amd64.whl'
CRT_WHEEL_SHA256 = '68c33d565cd4732be762d19ff67dfc53763256bac413d392aa8598b524980bc4'
CRT_WHEEL_DIRECTORY = 'https://files.pythonhosted.org/packages/a4/ea/a56b094a4bf6facf89f52f58e83684e168b1be08c14feb8b99969f3d4189'
CRT_FILES = {
    'msvcp140.dll': '5bc530e0f09b3f023cd81f28e9ae406f304f93ffcb81bde0656017fc2cf8ae7e',
    'vcomp140.dll': 'b7985a04701831e7a6b8f440428c8b55dcd696d97ccd298681a991c6e1adc858',
    'vcruntime140.dll': 'bbea6c008604b7d4a24f59ca093dfddf37be085759c0f5a46a8bbe6c3c0e173b',
    'vcruntime140_1.dll': '677c07f1f00b697e82986ff393305126c0ddee184712487945d80cd35b0f0823',
}


def cpu_runtime_directory(root):
    return Path(root) / 'tools' / 'crispasr' / RUNTIME_VERSION / 'cpu'


def runtime_files(device):
    return {**(BUNDLED_CPU_FILES if device == 'cpu' else CUDA_FILES), **CRT_FILES}


def _files_verified(folder, files):
    from ..model_integrity import sha256_file
    return all((folder / name).is_file() and sha256_file(folder / name) == expected
               for name, expected in files.items())


def _stage_crt(stage, bundled, downloads):
    if _files_verified(bundled, CRT_FILES):
        for name in CRT_FILES:
            shutil.copy2(bundled / name, stage / name)
        return
    wheel = WheelDownload(downloads, CRT_WHEEL, [CRT_WHEEL_SHA256],
                          [dict(label='PyPI', url=CRT_WHEEL_DIRECTORY, official=True)], family='CrispASR')
    wheel.fetch()
    with zipfile.ZipFile(wheel.target) as archive:
        for name in CRT_FILES:
            (stage / name).write_bytes(archive.read('shiboken6/' + name))


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
    from ..repository_download import preparation_lock

    if sys.platform != 'win32':
        raise RuntimeError('目前固定的 Haas 執行元件僅提供 Windows x64。')
    paths = get_runtime_paths()
    base = paths.managed_runtime_root / 'crispasr' / RUNTIME_VERSION
    with preparation_lock(base / f'.{device}.lock'):
        return _prepare_locked(device, base, cpu_runtime_directory(paths.install_root))


def _prepare_locked(device, base, bundled):
    found = runtime_executable(device)
    required = runtime_files(device)
    if found and _files_verified(found.parent, required) and _version(found, device):
        return found
    filename, expected = ARCHIVES[device]
    downloads = base / 'downloads'
    download = WheelDownload(downloads, filename, [expected],
                             [dict(label='CrispASR GitHub', url=SOURCE, official=True)],
                             family='CrispASR')
    existing = download.target.stat().st_size if download.target.is_file() else 0
    required_bytes = RUNTIME_BYTES[device] + max(0, ARCHIVE_BYTES[device] - existing)
    if shutil.disk_usage(base).free < required_bytes:
        raise RuntimeError(f'磁盘空间不足，Haas {device.upper()} 运行库需要 {required_bytes:,} 字节。')
    download.fetch()
    target = base / device
    with tempfile.TemporaryDirectory(dir=base, prefix=f'.{device}-') as temporary:
        stage = Path(temporary) / 'runtime'
        stage.mkdir()
        with zipfile.ZipFile(download.target) as package:
            entries = [item for item in package.infolist() if not item.is_dir()]
            for member in entries:
                name = Path(member.filename).name
                if name in required and name not in CRT_FILES:
                    with package.open(member) as origin, (stage / name).open('xb') as output:
                        shutil.copyfileobj(origin, output)
        _stage_crt(stage, bundled, downloads)
        if not _files_verified(stage, required) or not _version(stage / 'crispasr.exe', device):
            raise RuntimeError('正式 CrispASR 發行檔未包含有效執行檔或授權文件。')
        if target.exists():
            backup = Path(temporary) / 'previous'
            target.rename(backup)
            try:
                stage.rename(target)
            except OSError:
                backup.rename(target)
                raise
            return target / 'crispasr.exe'
        stage.rename(target)
    return target / 'crispasr.exe'
