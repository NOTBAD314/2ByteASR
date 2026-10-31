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
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# The package root (twobyteasr/) beside scripts/; main() also adds --root.
sys.path.append(str(Path(__file__).resolve().parents[1]))
from twobyteasr.system.runtime_package_download import (  # noqa: E402 - needs the path above
    RUNTIME_SOURCE_ENV, SourceFailed, SourcesExhausted, WheelDownload, fetch_files, files_for_hashes,
    load_package_files, describe_ranking, order_by_preference, pypi_sources, rank_sources, rate_text,
    runtime_preference, size_text)

# Fallback sources and the official hashes that make them safe to use.
RUNTIME_SOURCES = Path('scripts/runtime_sources.json')
PACKAGE_HASHES = Path('scripts/runtime_package_hashes.json')


class RemovedModelError(ValueError):
    """A retired key must be rejected before runtime/cache preparation."""


SOURCES_EXHAUSTED = 75
# CUDA PyTorch (2.4-3 GB) is fetched here rather than by uv: uv prints nothing
# until a file is complete, keeps nothing after a pause and changes source only
# on failure. Measured 2026-10-14 on a mainland line without proxy:
# download.pytorch.org gave ~1 MB/s (a 0.7.1 user's fast first 8 MB was no
# promise either) while the SJTU/NJU mirrors gave 17-47 MB/s for the same file.
# uv then installs the file from a local --find-links folder; every byte is
# checked against the locked SHA-256 first. Since 2026-10-28 the other locked
# packages are fetched the same way (twobyteasr/system/runtime_package_download.py)
# and uv installs the environment offline.
# Beside uv's own buckets: `uv cache prune` removes folders it does not know, so
# cache maintenance keeps and removes these files exactly like uv's downloads.
WHEELHOUSE = Path('download-cache/2byteasr-pytorch-wheels')
PYPI_HOUSE = Path('download-cache/2byteasr-pypi-files')
HEARTBEAT_S = 30.0
# 2026-10-21: on one PC Windows reported folders under %LOCALAPPDATA%\2ByteASR as in use (os error 32) whenever uv
# deleted them. Every `uv python install` re-creates the minor-version links (cpython-3.10-windows-x86_64-none), so it
# failed and left an empty folder where the link was; a temporary numba-*.data folder failed the same way once.
MINOR_VERSION_LINK = re.compile(r'^cpython-\d+\.\d+-windows-x86_64-none$')
IN_USE = re.compile(r'\(os error 32\)')
IN_USE_WAITS_S = (2.0, 5.0, 10.0)


def save(path, value):
    path = Path(path)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    os.replace(pending, path)


def read_runtime_receipt(path, role, known_models):
    """Read history without repairing/overwriting the original receipt.

    A damaged history is distinct from an empty historical selection. Callers
    must report the issue and use only their trusted current request.
    """
    try:
        value = json.loads(Path(path).read_text('utf8'))
        if not isinstance(value, dict) or value.get('role') != role:
            raise ValueError('运行环境清单不是预期角色的对象')
        models = value.get('models')
        if not isinstance(models, list) or any(not isinstance(x, str) or x not in known_models for x in models):
            raise ValueError('历史模型集合必须是当前支持的模型名称列表')
    except (OSError, ValueError, TypeError) as exc:
        return None, dict(role=role, receipt=str(path), historical_models='unavailable',
                          reason=type(exc).__name__+': '+str(exc), original_preserved=True)
    return value, None


def verified_bundled_build_wheels(root):
    """Require the exact two pure-Python build wheels, not a warm uv cache."""
    try:
        backend = json.loads((root/PACKAGE_HASHES).read_text('utf8'))['build_backend']
        manifest_path=root/'wheels/model_wheels.json'
        if not manifest_path.is_file():
            manifest_path=root/'packaging/model_wheels.json'  # source checkout layout
        manifest = json.loads(manifest_path.read_text('utf8'))['wheels']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('MOSS 离线构建缺少内置构建工具清单；请修复安装包。') from exc
    selected=[]
    for name in ('setuptools', 'wheel'):
        pin = backend.get(name, {})
        version = str(pin.get('version') or '')
        rows = [row for row in manifest if str(row.get('file','')).startswith(name+'-'+version+'-')
                and str(row.get('file','')).endswith('-none-any.whl')]
        if not version or len(rows) != 1:
            raise RuntimeError(f'MOSS 离线构建缺少已锁定的内置 {name}=={version} wheel；请修复安装包，未访问外网。')
        row=rows[0];path=root/'wheels'/row['file']
        if path.parent != root/'wheels' or not path.is_file():
            raise RuntimeError(f'MOSS 离线构建缺少内置文件 {row["file"]}；请修复安装包，未访问外网。')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row.get('sha256') or digest not in pin.get('sha256',[]):
            raise RuntimeError(f'MOSS 内置构建工具 SHA-256 校验失败：{row["file"]}；未访问外网。')
        selected.append(path)
    return selected


def install_moss_source_offline(uv, root, source, python, build, managed):
    """Build the bundled source with verified local backends, without an index."""
    wheels=verified_bundled_build_wheels(root)
    build.write_text(mirror_build_constraints(root), 'utf8')
    # Expose only the verified backends to isolated PEP 517 resolution. The
    # relative paths also avoid uv's whitespace splitting of constraints.
    with tempfile.TemporaryDirectory(prefix='moss-build-wheels-',dir=managed) as directory:
        folder=Path(directory)
        if not folder.resolve().is_relative_to(managed.resolve()):
            raise RuntimeError('MOSS 构建工具暂存目录越界')
        for wheel in wheels:
            target=folder/wheel.name
            shutil.copyfile(wheel,target)
            if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(wheel.read_bytes()).digest():
                raise RuntimeError('MOSS 构建工具暂存校验失败')
        uv('pip','install','--python',python,'--no-index','--offline',
           '--find-links',str(folder.relative_to(managed)),
           '--build-constraint',str(build.relative_to(managed)),
           '--no-deps',str(source)+'[torch-runtime]')


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


def create_pinned_venv(base, runtime, run):
    """Bind to the verified patch interpreter, never uv's mutable minor link.

    uv 0.11.7 rewrites even an explicit 3.10.19 path to cpython-3.10 when
    that folder is its managed install directory. An interrupted refresh of
    that link then leaves a surviving trampoline that cannot start Python.
    The pinned base's stdlib creator avoids that extra lifetime dependency.
    """
    base=Path(base).resolve();runtime=Path(runtime)
    run([base,'-I','-X','utf8','-m','venv','--without-pip',runtime], '创建运行环境')
    cfg={key.strip():value.strip() for key,value in
         (line.split('=',1) for line in (runtime/'pyvenv.cfg').read_text('utf8').splitlines() if '=' in line)}
    if Path(cfg.get('home','').strip()).resolve()!=base.parent:
        raise RuntimeError('新环境没有引用已验证的固定基础 Python；未登记此环境')


def validate_runtime(python, root, identity, managed):
    from twobyteasr.system.deployment import run_command
    run_command([python, '-I', '-X', 'utf8', '-B', root/'scripts/validate_managed_runtime.py',
                 '--managed', managed, '--identity', json.dumps(identity)],
                cwd=managed, phase='environment_checking', component=identity['role'], timeout=180)


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


def pytorch_wheel_name(pin, version):
    name, _, release = pin.partition('==')
    cpython = 'cp' + version.replace('.', '')[:3]
    return f'{name}-{release}-{cpython}-{cpython}-win_amd64.whl'


def pytorch_sources(root, tag, prefer_mirror):
    """Folders serving the same locked files: official first unless mirrors are preferred."""
    official = {'label': 'PyTorch 官方', 'url': f'https://download.pytorch.org/whl/{tag}', 'official': True}
    mirrors = [{'label': item['label'], 'url': item['url'].format(tag=tag).rstrip('/'), 'official': False}
               for item in mirror_list(root, 'pytorch_mirrors')]
    return [*mirrors, official] if prefer_mirror else [official, *mirrors]


def fetch_pytorch_wheels(folder, pins, version, entry, sources):
    """Fetch the locked PyTorch wheels into ``folder``; return why the official source was left."""
    reasons = []
    for index, pin in enumerate(pins, 1):
        name = pytorch_wheel_name(pin, version)
        hashes = entry['packages'][normalize(pin.split('==', 1)[0])]['sha256']
        reason = WheelDownload(folder, name, hashes, sources, index=index, count=len(pins)).fetch()
        if reason:
            reasons.append(reason)
            # Later files of this environment start where the bytes came from.
            sources = [item for item in sources if not item['official']] + [item for item in sources if item['official']]
    return reasons[0] if reasons else ''


def uv_step(arguments):
    """Short Chinese name of a uv command for heartbeat lines."""
    words = [str(item) for item in arguments if not str(item).startswith('-')]
    if words[:2] == ['python', 'install']:
        return '下载私有 Python'
    if words[:1] == ['venv']:
        return '创建运行环境'
    if words[:2] == ['pip', 'install']:
        return '下载并安装依赖'
    if words[:2] == ['pip', 'check']:
        return '检查依赖'
    return '运行 uv'


def python_install_dir(arguments):
    """The --install-dir of a `uv python install` command, else None."""
    words = [str(item) for item in arguments]
    if '--install-dir' not in words or not any(words[i:i + 2] == ['python', 'install'] for i in range(len(words))):
        return None
    return Path(words[words.index('--install-dir') + 1])


def remove_minor_version_links(folder):
    """Remove the minor-version links uv is about to re-create, so that it only has to create them.

    Only the link itself goes (os.rmdir on a junction never touches its target), plus an empty folder left where a
    link was by an earlier failed re-creation (uv cannot recover from that). Returns {link: target} for restoring.
    """
    removed = {}
    folder = Path(folder)
    if not folder.is_dir():
        return removed
    for entry in sorted(folder.iterdir()):
        if not MINOR_VERSION_LINK.match(entry.name):
            continue
        if getattr(os.lstat(entry), 'st_file_attributes', 0) & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            removed[entry] = os.readlink(entry)
            os.rmdir(entry)
        elif entry.is_dir() and not any(entry.iterdir()):
            os.rmdir(entry)
    return removed


def restore_minor_version_links(removed):
    """Re-create the links a failed uv call did not bring back, pointing where they pointed before."""
    for link, target in removed.items():
        if not os.path.lexists(link):
            import _winapi  # Windows only, like the link names
            _winapi.CreateJunction(target.removeprefix('\\\\?\\'), str(link))
            print(f'[运行库] 已恢复 Python 版本连接 {link.name}', flush=True)


def retry_when_in_use(call, label):
    """Run ``call`` again after a short wait when it failed only because Windows reported a file or folder as in
    use (os error 32); any other failure, and the last attempt, is raised as before."""
    for wait in (*IN_USE_WAITS_S, None):
        try:
            return call()
        except subprocess.CalledProcessError as error:
            if wait is None or not IN_USE.search(str(error.output or '')):
                raise
            print(f'[运行库] {label}：Windows 报告文件或文件夹正在被使用，{wait:g} 秒后重试', flush=True)
            time.sleep(wait)


def mirror_list(root, key):
    path = root / RUNTIME_SOURCES
    return list(json.loads(path.read_text('utf8')).get(key, [])) if path.is_file() else []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--models', required=True)
    parser.add_argument('--repair-roles', default='')
    args = parser.parse_args()
    requested = set(args.models.split(','))
    if requested & {'diarizen', 'diarizen_embedding', 'vibevoice_1_5b', 'vibevoice_7b'}:
        raise RemovedModelError('DiariZen / VibeVoice models have been removed; no installation or download was started.')
    root = args.root.resolve()
    sys.path.append(str(root))
    from twobyteasr.runtime_paths import managed_runtime_root
    from twobyteasr.system.runtime_registry import register_runtime, load_registry
    from twobyteasr.system.deployment import event, managed_environment, run_command
    # setup_managed_backend.ps1 passes the folder it locked (2BYTEASR_RUNTIME_ROOT).
    managed = managed_runtime_root()
    clean = managed_environment(runtime=managed)
    private_python = Path(os.environ.get('TWOBYTEASR_PRIVATE_PYTHON_DIR') or managed/'python')
    if not private_python.resolve().is_relative_to((managed/'python').resolve()):
        raise RuntimeError('专用 Python 目录越界')
    clean['UV_PYTHON_INSTALL_DIR'] = str(private_python)
    os.environ.clear()
    os.environ.update(clean)
    # Always use this app's cache; a caller's global UV_CACHE_DIR never leaks in.
    os.environ['UV_CACHE_DIR'] = str(managed / 'download-cache')
    # Hardlinks survive cache unlinking; symbolic links would tie installed
    # environments to a disposable package cache.
    os.environ['UV_LINK_MODE'] = 'hardlink'
    from twobyteasr.system.runtime_download_cache import mark_runtime_cache_state
    mark_runtime_cache_state('installing')
    contract = json.loads((root / 'dependencies.lock.json').read_text('utf-8-sig'))
    # The workshop's download source (download_models.ps1) applies to runtimes
    # too: "mirror" (ModelScope / HF 镜像) starts from domestic sources,
    # "official" (Hugging Face 官方) from the official ones, "auto" measures
    # every source before a download (2026-10-28). Once official PyTorch proved
    # slow or failed, or measuring found a mirror faster, later steps of this
    # run start from the mirrors as well.
    preference = runtime_preference()
    prefer_mirror = preference == 'mirror'
    mirror_reason = '已选择国内下载源' if prefer_mirror else ''
    if prefer_mirror:
        print('[运行库] 已选择国内下载源：运行环境先用国内镜像，每个文件仍按锁定 SHA-256 校验', flush=True)
    elif preference == 'auto':
        print('[运行库] 下载源为自动：下载前先测各来源的速度再排顺序，下载中慢了或停住会换来源接着下', flush=True)
    package_table = load_package_files(root)
    ranked = {}
    def ranked_sources(family, sources, path):
        """``sources`` in trial order for this run, measured once per family."""
        nonlocal prefer_mirror, mirror_reason
        effective = 'mirror' if prefer_mirror else preference
        if (family, effective) not in ranked:
            order, measured = rank_sources(sources, path, effective)
            print(f'[运行库] {family} 来源测速（各读同一文件的前 512 KiB）：{describe_ranking(order, measured)}', flush=True)
            ranked[(family, effective)] = order
            if preference == 'auto' and not prefer_mirror and order and not order[0].get('official') \
                    and measured[order[0]['label']]['rate'] > 0:
                prefer_mirror, mirror_reason = True, f"测速后 {order[0]['label']} 比官方来源快"
                print('[运行库] 测速结果国内镜像更快：本次之后的 Python、PyTorch 与依赖包都先用国内镜像', flush=True)
        return ranked[(family, effective)]
    def run(arguments, step='运行 uv'):
        print('[运行库] '+subprocess.list2cmdline([str(x) for x in arguments]), flush=True)
        # The application's Windows process policy defaults unspecified stdio
        # to DEVNULL. Explicit pipes keep bootstrap diagnostics visible.
        phase = 'environment_checking' if step == '检查依赖' else 'dependencies_installing'
        if step == '下载私有 Python': phase = 'interpreter_preparing'
        install_dir = python_install_dir(arguments)
        def attempt():
            links = remove_minor_version_links(install_dir) if install_dir else {}
            try:
                return run_command(arguments, cwd=managed, phase=phase, component=step,
                                   timeout=120 if phase=='environment_checking' else 900)
            finally:
                restore_minor_version_links(links)
        return retry_when_in_use(attempt, step)
    def uv(*arguments):
        # Existing venv files can share hardlinks with uv's expanded cache.
        # Explicit repair must not copy an in-place corruption back from it.
        run([args.uv, '--no-config', '--system-certs',
             *(['--no-cache'] if args.repair_roles else []), *arguments], uv_step(arguments))
    def install_python(version):
        base=private_python/f'cpython-{version}-windows-x86_64-none/python.exe'
        if base.is_file():
            try:
                run([base,'-I','-X','utf8','-c',f"import sys;assert '.'.join(map(str,sys.version_info[:3]))=={version!r}"], '检查基础 Python')
                return
            except (subprocess.CalledProcessError,RuntimeError,TimeoutError,OSError):
                pass
        install = ('python', 'install', version, '--install-dir', private_python, '--no-bin', '--no-registry')
        # uv checks every Python archive against the SHA-256 built into uv.
        attempts = [(None, '默认来源')] + [(item['url'], item['label']) for item in mirror_list(root, 'python_mirrors')]
        if prefer_mirror:
            attempts = attempts[1:] + attempts[:1]
        failure = None
        for number, (url, label) in enumerate(attempts):
            if number:
                print(f"[运行库] {attempts[number - 1][1]}未能取得 Python {version}，改用 {label}，由 uv 按内置 SHA-256 校验", flush=True)
            try:
                return uv(*install, *(('--mirror', url) if url else ()))
            except (subprocess.CalledProcessError, TimeoutError) as error:
                failure = failure or error
        raise SourcesExhausted(f'Python {version} 下载失败：默认来源与国内备用来源都没有成功') from failure
    wheel_manifest = root/'wheels/model_wheels.json'
    bundled_hashes = set()
    if wheel_manifest.is_file():
        for item in json.loads(wheel_manifest.read_text('utf8'))['wheels']:
            file = root/'wheels'/item['file']
            if file.parent != root/'wheels' or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
                raise RuntimeError('内置运行库资源校验失败：'+item['file'])
            bundled_hashes.add(item['sha256'])
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
    repair_roles = set(filter(None, args.repair_roles.split(',')))
    receipt_issues = {}
    def read_receipt(path, role):
        value, issue = read_runtime_receipt(path, role, set(contract['models']))
        if issue and str(path) not in receipt_issues:
            receipt_issues[str(path)] = issue
            event('environment_checking', 'warning', component=role,
                  reason='历史模型集合无法恢复；旧清单保留，本次仅依据可信的当前请求。',
                  receipt_issue=issue, current_request=sorted(requested),
                  repair_roles=sorted(repair_roles))
            print(f'[运行库] {role} 的历史模型集合无法恢复：{path}。旧清单原样保留；'
                  f'本次仅按当前请求与明确修复范围准备，未请求修复的角色保持原登记。',flush=True)
        return value
    # The same pinned main contract underlies standard adapters. Union only the
    # app-managed selection, and create a new environment when the set changes.
    previous_main_models = set()
    previous = registry.get('main', {}).get('python_executable', '')
    if previous and Path(previous).resolve().is_relative_to(managed.resolve()):
        receipt = Path(previous).parent.parent / 'managed-runtime.json'
        previous_identity=read_receipt(receipt,'main')
        if previous_identity is not None:
            previous_main_models.update(previous_identity['models'])
    for role, models in planned_roles(requested, previous_main_models):
        if repair_roles and role not in repair_roles: continue
        env_contract = contract['environments'][role]
        packages = role_packages(contract, role, models)
        version = role_python(role)
        identity = dict(role=role, models=sorted(models), packages=packages, python=version,
                        torch=env_contract['torch'] if models else None, tag=tag, schema=1)
        # Model labels describe the consumers; the runtime identity is the
        # interpreter and dependency contract. Adding an aligner already
        # covered by qwen-asr must not reinstall an identical multi-GB venv.
        signature = hashlib.sha256(json.dumps(
            {key:value for key,value in identity.items() if key!='models'},sort_keys=True).encode()).hexdigest()[:16]
        runtime = managed / role / signature
        registered = registry.get(role, {}).get('python_executable', '')
        if registered:
            candidate = Path(registered).parent.parent
            if candidate.resolve().is_relative_to((managed/role).resolve()):
                old_identity = read_receipt(candidate/'managed-runtime.json',role)
                if old_identity is not None and all(old_identity.get(k)==v for k,v in identity.items() if k!='models'):
                    runtime = candidate
        python = runtime / 'Scripts/python.exe'
        receipt = runtime / 'managed-runtime.json'
        saved_identity=read_receipt(receipt,role) if runtime.exists() else None
        matching_identity=(saved_identity is not None and all(saved_identity.get(k)==v for k,v in identity.items() if k!='models'))
        if matching_identity and python.is_file() and role not in repair_roles:
            try:
                uv('pip', 'check', '--python', python)
                validate_runtime(python, root, identity, managed)
            except (subprocess.CalledProcessError, RuntimeError, TimeoutError, OSError) as exc:
                event('environment_checking', 'failed', component=role, reason=str(exc), next='rebuild_new_directory')
            else:
                if saved_identity.get('models')!=identity['models']:
                    save(receipt,dict(saved_identity,**identity))
                register_runtime(role, str(python), source='managed-model-bootstrap')
                print('[运行库] 复用已验证环境 '+str(runtime), flush=True)
                continue
        # Never install over a damaged or interrupted environment and never
        # move a venv after creation (uv launchers contain absolute paths).
        if runtime.exists():
            runtime = managed/role/(signature+'-'+uuid.uuid4().hex[:8])
            python = runtime/'Scripts/python.exe'
            receipt = runtime/'managed-runtime.json'
        event('environment_building', component=role, target=str(runtime), previous=registered,
              reason='explicit_repair' if role in repair_roles else 'missing_or_invalid')
        base = private_python / f'cpython-{version}-windows-x86_64-none/python.exe'
        install_python(version)
        if not python.is_file():
            create_pinned_venv(base,runtime,run)
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
        entry = hashed_environment(root, role, version, tag, pins)[0]
        # The CPU build ships in wheels/; a CUDA build is fetched by this script
        # (resumable, with progress) when its file is in the locked hash table.
        cpython = 'cp' + version.replace('.', '')[:3]
        local_torch = bool(links) and all(any((root/'wheels').glob(f"{pin.replace('==', '-')}-{cpython}-*.whl")) for pin in torch_pins)
        left_official = ''
        if torch_pins and not local_torch and entry:
            wheelhouse = managed / WHEELHOUSE
            first_wheel = quote(pytorch_wheel_name(torch_pins[0], version), safe='')
            left_official = fetch_pytorch_wheels(wheelhouse, torch_pins, version, entry, ranked_sources(
                f'PyTorch {tag}', pytorch_sources(root, tag, prefer_mirror), first_wheel))
            links = [*links, '--find-links', str(wheelhouse)]
            local_torch = True
            if left_official and not prefer_mirror:
                prefer_mirror, mirror_reason = True, left_official
                print('[运行库] 本次官方 PyTorch 来源不理想，之后的环境直接先用国内镜像', flush=True)
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
            binary_only = [arg for name in entry['packages'] if name not in entry.get('sdist_only', [])
                           for arg in ('--only-binary', name)]
            # 2026-10-28: the app fetches every locked file uv could need that
            # is not bundled (measured order, resumable, switching source when
            # slow or stalled), then uv installs offline. uv on its own waits
            # on a slow source for up to the 900-second step limit.
            wanted = {name: item['sha256'] for name, item in entry['packages'].items()
                      if '+' not in item['version'] and not set(item['sha256']) & bundled_hashes}
            items = files_for_hashes(package_table, wanted)
            measured_order = []
            if items is None:
                print('[运行库] 本程序包的依赖文件清单不全，由 uv 从软件源安装', flush=True)
            else:
                house = managed / PYPI_HOUSE
                house.mkdir(parents=True, exist_ok=True)
                try:
                    if items:
                        sources = ranked_sources('PyPI', pypi_sources(mirror_list(root, 'pypi_mirrors')),
                                                 max(items, key=lambda item: item['size'])['path'])
                        measured_order = [source['label'] for source in sources]
                        fetch_files(house, items, sources, family='依赖包', display='PyPI')
                    event('dependencies_installing', component=role, attempt=1, source='local', reason=why,
                          allowed_source_builds=entry.get('sdist_only', []))
                    print('[运行库] 依赖文件都已在本机并通过 SHA-256 校验，离线安装（uv 不再连接软件源）', flush=True)
                    uv('pip', 'install', '--python', python, '--no-index', *links, '--find-links', str(house),
                       '--constraint', str(hashed.relative_to(managed)),
                       '--build-constraint', str(build.relative_to(managed)), *binary_only, *requirements)
                    mirror.update(entry=entry, used=True, index='local', constraints=str(hashed.relative_to(managed)))
                    return
                except (SourcesExhausted, RuntimeError, OSError, subprocess.CalledProcessError, TimeoutError) as error:
                    print(f'[运行库] 应用内下载或离线安装没有完成（{error}），改由 uv 依次从软件源安装', flush=True)
            # PyTorch is already on disk here (bundled CPU build or a verified
            # download in the wheelhouse), so only PyPI needs a mirror.
            official_index = dict(label='PyPI 官方',url='https://pypi.org/simple')
            indexes = mirror_list(root, 'pypi_mirrors')
            indexes = indexes+[official_index] if prefer_mirror else [official_index]+indexes
            if measured_order:
                indexes.sort(key=lambda row: measured_order.index(row['label']) if row['label'] in measured_order else len(measured_order))
            for attempt, pypi in enumerate(indexes, 1):
                event('dependencies_installing', component=role, attempt=attempt, source=pypi['label'],
                      reason=why if attempt==1 else 'previous_source_failed', allowed_source_builds=entry.get('sdist_only',[]))
                print(f"[运行库] {pypi['label']}（{attempt}/{len(indexes)}）；固定版本与 SHA-256 校验；只允许已声明的纯 Python 源码包构建", flush=True)
                # USTC answers uv's default parallel downloads with HTTP 429
                # (measured 2026-10-14); its entry lowers the concurrency.
                limit = str(pypi.get('concurrent_downloads') or '')
                saved = os.environ.get('UV_CONCURRENT_DOWNLOADS')
                if limit:
                    os.environ['UV_CONCURRENT_DOWNLOADS'] = limit
                try:
                    uv('pip', 'install', '--python', python, '--index-url', pypi['url'], *links,
                       '--constraint', str(hashed.relative_to(managed)),
                       '--build-constraint', str(build.relative_to(managed)), *binary_only, *requirements)
                except (subprocess.CalledProcessError, TimeoutError):
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
        if entry:
            why = left_official or mirror_reason or '固定依赖清单'
            install_from_mirrors(RuntimeError(why), why=why)
        else:
            raise RuntimeError(f'锁定哈希表缺少 {role} 环境的当前版本组合；未尝试未锁定依赖，请导出诊断。')
        if models:
            official_or_mirror(['--index-url', f'https://download.pytorch.org/whl/{tag}', *links], torch_pins)
        official_or_mirror(['--index-url', 'https://pypi.org/simple', *links, '--constraint', constraint_arg], package_pins)
        if source is not None:
            install_moss_source_offline(uv,root,source,python,build,managed)
        if models & {'firered_vad','firered_aed','firered_llm'}:
            firered = root / contract['sources']['firered']['path']
            if not (firered/'fireredasr2s/__init__.py').is_file():
                raise RuntimeError('安装包缺少已锁定 FireRed 源码；不需要系统 Git')
        uv('pip', 'check', '--python', python)
        validate_runtime(python, root, identity, managed)
        frozen = run_command([args.uv,'--no-config','pip','freeze','--python',python],
            cwd=managed,phase='environment_checking',component=role+' package inventory',timeout=120,capture=True).encode('utf8')
        if mirror['used']:
            verify_mirror_install(frozen.decode('utf8', 'replace'), mirror['entry'])
        (runtime/'installed.lock.txt').write_bytes(frozen)
        save(receipt, dict(identity, prepared_at=time.time(), previous_runtime=registered,
                           previous_receipt_issues=list(receipt_issues.values()),
                           historical_models_complete=not any(x['role']==role for x in receipt_issues.values())))
        from twobyteasr.local_models.model_runtime_cleanup import write_runtime_inventory
        write_runtime_inventory(runtime)
        register_runtime(role, str(python), source='managed-model-bootstrap')
        event('runtime_ready', 'done', component=role, interpreter=str(python), previous=registered)
    from twobyteasr.system.runtime_download_cache import mark_runtime_cache_ready
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
        from twobyteasr.system.runtime_download_cache import mark_runtime_cache_state
        mark_runtime_cache_state('paused')
        if isinstance(error, SourcesExhausted):
            # setup_managed_backend.ps1 reports this exit code as a network failure.
            print(f'[运行库] {error}', file=sys.stderr, flush=True)
            sys.exit(SOURCES_EXHAUSTED)
        raise
