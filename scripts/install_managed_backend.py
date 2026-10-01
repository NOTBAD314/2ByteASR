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
import subprocess
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def save(path, value):
    path = Path(path)
    pending = path.with_suffix(path.suffix + '.pending')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    os.replace(pending, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--models', required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.append(str(root))
    from twobyteasr.runtime_paths import user_data_root
    from twobyteasr.runtime_registry import register_runtime, load_registry
    managed = user_data_root() / 'runtimes'
    contract = json.loads((root / 'dependencies.lock.json').read_text('utf-8-sig'))
    requested = set(args.models.split(','))
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
    main_models = requested - {'moss', 'firered_llm', 'nemotron', 'omni_asr_llm_7b'}
    # The same pinned main contract underlies standard adapters. Union only the
    # app-managed selection, and create a new environment when the set changes.
    previous = registry.get('main', {}).get('python_executable', '')
    if previous and Path(previous).resolve().is_relative_to(managed.resolve()):
        receipt = Path(previous).parent.parent / 'managed-runtime.json'
        if receipt.is_file():
            previous_identity=json.loads(receipt.read_text('utf8'))
            if previous_identity.get('role')!='main':
                raise RuntimeError('主运行库注册角色不匹配，拒绝把其他模型环境当作 main 覆盖。')
            main_models.update(previous_identity.get('models', []))
    roles = [('main', main_models)]
    if 'moss' in requested: roles.append(('moss', {'moss'}))
    if 'firered_llm' in requested: roles.append(('firered_llm', {'firered_llm'}))
    if 'glm_asr_nano' in requested: roles.append(('glm_asr', {'glm_asr_nano'}))
    if 'canary_qwen' in requested: roles.append(('canary', {'canary_qwen'}))
    for role, models in roles:
        env_contract = contract['environments'][role]
        packages = dict(env_contract['packages']) if models else {}
        packages['requests'] = '2.33.0'
        if models & {'sensevoice', 'paraformer', 'funasr_nano'}: packages['funasr'] = '1.4.1'
        if models & {'qwen_asr', 'qwen_aligner'}: packages['qwen-asr'] = '0.0.6'
        if models & {'speaker_embedding', 'moss'}: packages['speechbrain'] = '1.0.3'
        if models & {'firered_vad', 'firered_aed'}: packages['sentencepiece'] = '0.2.2'
        if role == 'moss':
            packages.update(soundfile='0.14.0', kaldiio='2.18.1')
        version = '3.12.13' if role in {'moss','glm_asr','canary'} else '3.10.19'
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
        uv('python', 'install', version, '--install-dir', managed/'python', '--no-bin', '--no-registry')
        if not python.is_file():
            uv('venv', '--no-project', '--python', base, '--managed-python', '--no-python-downloads', runtime)
        constraints=runtime/'constraints.txt'
        pins=[f'{name.split("[")[0]}=={value}' for name,value in packages.items()]
        if models:pins.extend([f'torch=={env_contract["torch"]}+{tag}',f'torchaudio=={env_contract["torchaudio"]}+{tag}'])
        constraints.write_text('\n'.join(pins)+'\n','utf8')
        # uv 0.11.7 splits --constraint values on spaces, even when the OS
        # receives one quoted argument. Commands run in managed, so this
        # role/signature-relative path preserves user/install paths verbatim.
        constraint_arg = str(constraints.relative_to(managed))
        links = ['--find-links', str(root/'wheels')] if (root/'wheels').is_dir() else []
        if models:
            uv('pip', 'install', '--python', python, '--index-url', f'https://download.pytorch.org/whl/{tag}',
               *links, f"torch=={env_contract['torch']}+{tag}", f"torchaudio=={env_contract['torchaudio']}+{tag}")
        uv('pip', 'install', '--python', python, '--index-url', 'https://pypi.org/simple', *links,
           '--constraint',constraint_arg,
           *[f'{key}=={value}' for key, value in packages.items()])
        if role == 'moss':
            source = root / contract['sources']['moss']['path']
            if not (source/'pyproject.toml').is_file():
                raise RuntimeError('安装包缺少已锁定的 MOSS 源码，请修复安装包；不需要系统 Git')
            uv('pip', 'install', '--python', python, *links, '--constraint',constraint_arg,str(source)+'[torch-runtime]')
        if models & {'firered_vad','firered_aed','firered_llm'}:
            source = root / contract['sources']['firered']['path']
            if not (source/'fireredasr2s/__init__.py').is_file():
                raise RuntimeError('安装包缺少已锁定 FireRed 源码；不需要系统 Git')
        uv('pip', 'check', '--python', python)
        frozen = subprocess.check_output([str(args.uv),'--no-config','pip','freeze','--python',str(python)],
                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (runtime/'installed.lock.txt').write_bytes(frozen)
        save(receipt, dict(identity, prepared_at=time.time()))
        register_runtime(role, str(python), source='managed-model-bootstrap')


if __name__ == '__main__':
    main()
