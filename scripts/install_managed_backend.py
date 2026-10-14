"""Production model dependencies in immutable, application-managed environments.

Launched by setup_managed_backend.ps1 under an explicit managed interpreter.
The GUI executable is never used as Python. All publication follows pip check.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Fallback sources and the official hashes that make them safe to use.
RUNTIME_SOURCES = Path('scripts/runtime_sources.json')
PACKAGE_HASHES = Path('scripts/runtime_package_hashes.json')


class RemovedModelError(ValueError):
    """A retired key must be rejected before runtime/cache preparation."""


class SourcesExhausted(RuntimeError):
    """Official and fallback sources all failed (exit code SOURCES_EXHAUSTED)."""


SOURCES_EXHAUSTED = 75
# CUDA PyTorch is ~3 GB. Measured 2026-10-14 on a mainland line without proxy:
# download.pytorch.org answered at ~1 MB/s (the GUI run spent 30+ minutes on it)
# while the SJTU/NJU mirrors gave 17-22 MB/s for the same file. uv only falls
# back on failure, so a slow-but-working official host is measured first.
SPEED_PROBE_BYTES = 8 << 20
SLOW_OFFICIAL_BYTES_PER_SECOND = 2 << 20


def save(path, value):
    path = Path(path)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    os.replace(pending, path)


def role_python(role):
    return '3.12.13' if role in {'moss', 'glm_asr', 'canary'} else '3.10.19'


def planned_roles(requested, previous_main_models=()):
    main_models = (set(requested) - {'moss', 'firered_llm', 'omni_asr_llm_7b'}) | set(previous_main_models)
    roles = [('main', main_models)]
    if 'moss' in requested: roles.append(('moss', {'moss'}))
    if 'firered_llm' in requested: roles.append(('firered_llm', {'firered_llm'}))
    if 'glm_asr_nano' in requested: roles.append(('glm_asr', {'glm_asr_nano'}))
    if 'canary_qwen' in requested: roles.append(('canary', {'canary_qwen'}))
    return roles


def role_packages(contract, role, models):
    env_contract = contract['environments'][role]
    packages = dict(env_contract['packages']) if models else {}
    packages['requests'] = '2.33.0'
    if models & {'sensevoice', 'paraformer', 'funasr_nano'}: packages['funasr'] = '1.4.1'
    if models & {'qwen_asr', 'qwen_aligner'}: packages['qwen-asr'] = '0.0.6'
    if models & {'speaker_embedding', 'moss'}: packages['speechbrain'] = '1.0.3'
    if models & {'firered_vad', 'firered_aed'}: packages['sentencepiece'] = '0.2.2'
    if role == 'moss':
        packages.update(soundfile='0.14.0', kaldiio='2.18.1')
    return packages


def role_pins(contract, role, models, tag):
    packages = role_packages(contract, role, models)
    pins = [f'{name.split("[")[0]}=={value}' for name, value in packages.items()]
    if models:
        env_contract = contract['environments'][role]
        pins.extend([f'torch=={env_contract["torch"]}+{tag}', f'torchaudio=={env_contract["torchaudio"]}+{tag}'])
    return pins


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def hashed_environment(root, role, version, tag, pins):
    """Official-hash table for one environment, or None with the reason."""
    path = root / PACKAGE_HASHES
    if not path.is_file():
        return None, '安装包缺少锁定哈希表'
    entry = json.loads(path.read_text('utf8'))['environments'].get(f'{role}|{version}|{tag}')
    if not entry:
        return None, f'锁定哈希表没有 {role} / Python {version} / {tag}'
    for pin in pins:
        name, _, version_pin = pin.partition('==')
        item = entry['packages'].get(normalize(name))
        if not item or item['version'] != version_pin:
            return None, f'锁定哈希表与当前依赖版本不一致（{pin}）'
    return entry, ''


def probe_rate(url, limit_s=10.0):
    """Bytes/s over the first SPEED_PROBE_BYTES of ``url``; 0.0 when it cannot be read."""
    import urllib.request
    request = urllib.request.Request(url, headers={'Range': f'bytes=0-{SPEED_PROBE_BYTES - 1}',
                                                   'User-Agent': '2ByteASR-runtime-probe'})
    started = time.monotonic()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            while received < SPEED_PROBE_BYTES and time.monotonic() - started < limit_s:
                block = response.read(1 << 16)
                if not block:
                    break
                received += len(block)
    except Exception:  # noqa: BLE001 - unreachable counts as 0
        return 0.0
    return received / max(time.monotonic() - started, 1e-3)


def slow_official_pytorch(root, tag, version, torch_pins):
    """Reason to skip download.pytorch.org for this environment, or None.

    Only for CUDA builds (the CPU build ships in wheels/), and only when the
    official host is both slow in absolute terms and far slower than the first
    domestic mirror; overseas users keep the official source.
    """
    mirrors = mirror_list(root, 'pytorch_mirrors')
    if tag == 'cpu' or not torch_pins or not mirrors:
        return None
    cpython = 'cp' + version.replace('.', '')[:3]
    name = f"torch-{quote(torch_pins[0].split('==', 1)[1], safe='')}-{cpython}-{cpython}-win_amd64.whl"
    official = probe_rate(f'https://download.pytorch.org/whl/{tag}/{name}')
    if official >= SLOW_OFFICIAL_BYTES_PER_SECOND:
        return None
    mirror = probe_rate(mirrors[0]['url'].format(tag=tag).rstrip('/') + '/' + name)
    print(f"[运行库] PyTorch 下载测速：官方 {official / 2**20:.1f} MB/s，{mirrors[0]['label']} {mirror / 2**20:.1f} MB/s", flush=True)
    if mirror > 3 * official:
        state = f"只有 {official / 2**20:.1f} MB/s" if official else "连不上"
        return f"官方 PyTorch 来源{state}，{mirrors[0]['label']} {mirror / 2**20:.1f} MB/s"
    return None


def mirror_list(root, key):
    path = root / RUNTIME_SOURCES
    return list(json.loads(path.read_text('utf8')).get(key, [])) if path.is_file() else []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--models', required=True)
    args = parser.parse_args()
    requested = set(args.models.split(','))
    if requested & {'diarizen', 'diarizen_embedding', 'vibevoice_1_5b', 'vibevoice_7b'}:
        raise RemovedModelError('DiariZen / VibeVoice models have been removed; no installation or download was started.')
    root = args.root.resolve()
    sys.path.append(str(root))
    from twobyteasr.runtime_paths import user_data_root
    from twobyteasr.runtime_registry import register_runtime, load_registry
    managed = user_data_root() / 'runtimes'
    # Always use this app's cache; a caller's global UV_CACHE_DIR never leaks in.
    os.environ['UV_CACHE_DIR'] = str(managed / 'download-cache')
    # Hardlinks survive cache unlinking; symbolic links would tie installed
    # environments to a disposable package cache.
    os.environ['UV_LINK_MODE'] = 'hardlink'
    from twobyteasr.runtime_download_cache import mark_runtime_cache_state
    mark_runtime_cache_state('installing')
    contract = json.loads((root / 'dependencies.lock.json').read_text('utf-8-sig'))
    def run(arguments):
        print('[运行库] '+subprocess.list2cmdline([str(x) for x in arguments]), flush=True)
        # The application's Windows process policy defaults unspecified stdio
        # to DEVNULL. Explicit pipes keep bootstrap diagnostics visible.
        process=subprocess.Popen([str(x) for x in arguments],cwd=managed,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for line in process.stdout:print(line,end='',flush=True)
        code=process.wait()
        if code:raise subprocess.CalledProcessError(code,[str(x) for x in arguments])
    def uv(*arguments):
        run([args.uv, '--no-config', '--system-certs', *arguments])
    def install_python(version):
        install = ('python', 'install', version, '--install-dir', managed/'python', '--no-bin', '--no-registry')
        try:
            return uv(*install)
        except subprocess.CalledProcessError as error:
            failure = error
        for mirror in mirror_list(root, 'python_mirrors'):
            # uv checks every Python archive against the SHA-256 built into uv.
            print(f"[运行库] 默认来源未能取得 Python {version}，改用 {mirror['label']}，由 uv 按内置 SHA-256 校验", flush=True)
            try:
                return uv(*install, '--mirror', mirror['url'])
            except subprocess.CalledProcessError:
                continue
        raise SourcesExhausted(f'Python {version} 下载失败：默认来源与国内备用来源都没有成功') from failure
    wheel_manifest = root/'wheels/model_wheels.json'
    if wheel_manifest.is_file():
        for item in json.loads(wheel_manifest.read_text('utf8'))['wheels']:
            file = root/'wheels'/item['file']
            if file.parent != root/'wheels' or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
                raise RuntimeError('内置运行库资源校验失败：'+item['file'])
        print('[运行库] 内置 wheels 已通过上游发布 SHA256 校验；缺失依赖从官方包源补齐。',flush=True)
    tag = 'cpu'
    if not os.environ.get('2BYTEASR_CPU_ONLY'):
        nvidia = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/nvidia-smi.exe'
        if nvidia.is_file():
            result = subprocess.run([str(nvidia), '--query-gpu=compute_cap', '--format=csv,noheader'],
                                    capture_output=True, text=True, timeout=15,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                major = int(result.stdout.strip().split('.')[0])
                tag = contract['runtime']['cuda_wheel_modern' if major >= 12 else 'cuda_wheel']
    registry = load_registry()
    # The same pinned main contract underlies standard adapters. Union only the
    # app-managed selection, and create a new environment when the set changes.
    previous_main_models = set()
    previous = registry.get('main', {}).get('python_executable', '')
    if previous and Path(previous).resolve().is_relative_to(managed.resolve()):
        receipt = Path(previous).parent.parent / 'managed-runtime.json'
        if receipt.is_file():
            previous_identity=json.loads(receipt.read_text('utf8'))
            if previous_identity.get('role')!='main':
                raise RuntimeError('主运行库注册角色不匹配，拒绝把其他模型环境当作 main 覆盖。')
            previous_main_models.update(previous_identity.get('models', []))
    for role, models in planned_roles(requested, previous_main_models):
        env_contract = contract['environments'][role]
        packages = role_packages(contract, role, models)
        version = role_python(role)
        identity = dict(role=role, models=sorted(models), packages=packages, python=version,
                        torch=env_contract['torch'] if models else None, tag=tag, schema=1)
        signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        runtime = managed / role / signature
        python = runtime / 'Scripts/python.exe'
        receipt = runtime / 'managed-runtime.json'
        if receipt.is_file() and python.is_file():
            uv('pip', 'check', '--python', python)
            register_runtime(role, str(python), source='managed-model-bootstrap')
            print('[运行库] 复用已验证环境 '+str(runtime), flush=True)
            continue
        base = managed / 'python' / f'cpython-{version}-windows-x86_64-none/python.exe'
        install_python(version)
        if not python.is_file():
            uv('venv', '--no-project', '--python', base, '--managed-python', '--no-python-downloads', runtime)
        constraints=runtime/'constraints.txt'
        pins=role_pins(contract, role, models, tag)
        constraints.write_text('\n'.join(pins)+'\n','utf8')
        # uv 0.11.7 splits --constraint values on spaces, even when the OS
        # receives one quoted argument. Commands run in managed, so this
        # role/signature-relative path preserves user/install paths verbatim.
        constraint_arg = str(constraints.relative_to(managed))
        links = ['--find-links', str(root/'wheels')] if (root/'wheels').is_dir() else []
        torch_pins = pins[-2:] if models else []
        package_pins = [f'{key}=={value}' for key, value in packages.items()]
        source = root / contract['sources']['moss']['path'] if role == 'moss' else None
        mirror = {'entry': None, 'used': False}
        build = runtime/'mirror-build-constraints.txt'
        def install_from_mirrors(failure, why='官方来源未成功'):
            # Once an official source fails, the whole environment (PyTorch,
            # packages, MOSS dependencies) is installed from mirrors in one
            # resolution. Every package of the closure is pinned with its
            # official SHA-256, which uv verifies. Only wheel hashes are listed
            # where a wheel exists, so a mirror cannot swap in a source build;
            # the few source-only packages build with setuptools/wheel that
            # are hash-pinned as well (--build-constraint).
            entry, reason = hashed_environment(root, role, version, tag, pins)
            if not entry:
                raise RuntimeError(f'官方来源未成功，且不能安全改用镜像：{reason}') from failure
            hashed = runtime/'mirror-constraints.txt'
            hashed.write_text(''.join(
                f"{name}=={item['version']} " + ' '.join('--hash=sha256:'+value for value in item['sha256']) + '\n'
                for name, item in sorted(entry['packages'].items())), 'utf8')
            build.write_text(mirror_build_constraints(root), 'utf8')
            requirements = [*torch_pins, *package_pins, *pinned_names(entry, entry.get('extra_requirements', []))]
            # The CPU build ships in wheels/; only CUDA builds need a PyTorch mirror.
            cpython = 'cp' + version.replace('.', '')[:3]
            bundled = links and all(any((root/'wheels').glob(f"{pin.replace('==', '-')}-{cpython}-*.whl")) for pin in torch_pins)
            torch_mirrors = mirror_list(root, 'pytorch_mirrors') if torch_pins and not bundled else [None]
            for pypi in mirror_list(root, 'pypi_mirrors'):
                for torch_mirror in torch_mirrors or [None]:
                    torch_links = []
                    if torch_mirror:
                        base_url = torch_mirror['url'].format(tag=tag).rstrip('/')
                        torch_links = ['--find-links', base_url+'/torch/', '--find-links', base_url+'/torchaudio/']
                    label = pypi['label'] + (' + ' + torch_mirror['label'] if torch_mirror else '')
                    print(f'[运行库] {why}，改用 {label}；每个包都按锁定 SHA-256 校验', flush=True)
                    # USTC answers uv's default parallel downloads with HTTP 429
                    # (measured 2026-10-14); its entry lowers the concurrency.
                    limit = str(pypi.get('concurrent_downloads') or '')
                    saved = os.environ.get('UV_CONCURRENT_DOWNLOADS')
                    if limit:
                        os.environ['UV_CONCURRENT_DOWNLOADS'] = limit
                    try:
                        uv('pip', 'install', '--python', python, '--index-url', pypi['url'], *torch_links, *links,
                           '--constraint', str(hashed.relative_to(managed)),
                           '--build-constraint', str(build.relative_to(managed)), *requirements)
                    except subprocess.CalledProcessError:
                        continue
                    finally:
                        if limit and saved is None:
                            os.environ.pop('UV_CONCURRENT_DOWNLOADS', None)
                        elif limit:
                            os.environ['UV_CONCURRENT_DOWNLOADS'] = saved
                    mirror.update(entry=entry, used=True, index=pypi['url'], constraints=str(hashed.relative_to(managed)))
                    return
            raise SourcesExhausted('运行库下载失败：官方来源与国内镜像都没有成功') from failure
        def official_or_mirror(official, requirements):
            if mirror['used']:
                return  # the mirror resolution already covered this step
            try:
                uv('pip', 'install', '--python', python, *official, *requirements)
            except subprocess.CalledProcessError as error:
                install_from_mirrors(error)
        if source is not None and not (source/'pyproject.toml').is_file():
            raise RuntimeError('安装包缺少已锁定的 MOSS 源码，请修复安装包；不需要系统 Git')
        if models and hashed_environment(root, role, version, tag, pins)[0]:
            slow = slow_official_pytorch(root, tag, version, torch_pins)
            if slow:
                install_from_mirrors(RuntimeError(slow), why=slow)
        if models:
            official_or_mirror(['--index-url', f'https://download.pytorch.org/whl/{tag}', *links], torch_pins)
        official_or_mirror(['--index-url', 'https://pypi.org/simple', *links, '--constraint', constraint_arg], package_pins)
        if source is not None:
            moss_target = str(source)+'[torch-runtime]'
            official_or_mirror([*links, '--constraint', constraint_arg], [moss_target])
            if mirror['used']:
                # Its dependencies came with the mirror resolution above; the
                # locked source is built with the hash-pinned build backend.
                uv('pip', 'install', '--python', python, '--index-url', mirror['index'], *links,
                   '--constraint', mirror['constraints'], '--build-constraint', str(build.relative_to(managed)), moss_target)
        if models & {'firered_vad','firered_aed','firered_llm'}:
            firered = root / contract['sources']['firered']['path']
            if not (firered/'fireredasr2s/__init__.py').is_file():
                raise RuntimeError('安装包缺少已锁定 FireRed 源码；不需要系统 Git')
        uv('pip', 'check', '--python', python)
        frozen = subprocess.check_output([str(args.uv),'--no-config','pip','freeze','--python',str(python)],
                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if mirror['used']:
            verify_mirror_install(frozen.decode('utf8', 'replace'), mirror['entry'])
        (runtime/'installed.lock.txt').write_bytes(frozen)
        save(receipt, dict(identity, prepared_at=time.time()))
        from twobyteasr.model_runtime_cleanup import write_runtime_inventory
        write_runtime_inventory(runtime)
        register_runtime(role, str(python), source='managed-model-bootstrap')
    from twobyteasr.runtime_download_cache import mark_runtime_cache_ready
    mark_runtime_cache_ready()


def pinned_names(entry, requirements):
    """Pin each requirement (e.g. MOSS's "librosa>=0.11.0") to its locked version."""
    pins = []
    for requirement in requirements:
        name = normalize(re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)', requirement).group(1))
        item = entry['packages'].get(name)
        if not item:
            raise RuntimeError(f'锁定哈希表缺少 {name}')
        pins.append(f"{name}=={item['version']}")
    return pins


def mirror_build_constraints(root):
    """Source builds on the mirror path use the locked setuptools/wheel only."""
    backend = json.loads((root/PACKAGE_HASHES).read_text('utf8'))['build_backend']
    return ''.join(f"{name}=={item['version']} " + ' '.join('--hash=sha256:'+value for value in item['sha256']) + '\n'
                   for name, item in sorted(backend.items()))


def verify_mirror_install(frozen, entry):
    """Everything installed from a mirror must be a locked, hash-checked file."""
    unexpected = []
    for line in frozen.splitlines():
        name, separator, version = line.strip().partition('==')
        if not separator:
            continue  # the local MOSS source, recorded as "name @ file://..."
        item = entry['packages'].get(normalize(name))
        if not item or item['version'] != version:
            unexpected.append(line.strip())
    if unexpected:
        raise RuntimeError('镜像安装出现锁定哈希表之外的包：' + '、'.join(unexpected))


if __name__ == '__main__':
    try:
        main()
    except RemovedModelError:
        raise
    except BaseException as error:
        from twobyteasr.runtime_download_cache import mark_runtime_cache_state
        mark_runtime_cache_state('paused')
        if isinstance(error, SourcesExhausted):
            # setup_managed_backend.ps1 reports this exit code as a network failure.
            print(f'[运行库] {error}', file=sys.stderr, flush=True)
            sys.exit(SOURCES_EXHAUSTED)
        raise
