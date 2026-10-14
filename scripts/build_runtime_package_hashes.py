"""Regenerate scripts/runtime_package_hashes.json from the official indexes.

The model runtime installs from pypi.org and download.pytorch.org. When those
fail, install_managed_backend.py may use a domestic mirror, but only for files
whose SHA-256 is listed here. For each environment (role / Python / PyTorch
build) the table pins one version per package over the union of all models of
that role, so any model subset resolves inside it.

Run after changing dependencies.lock.json environments, the role package rules
in install_managed_backend.py, or the MOSS source. Needs Python 3.11+ (tomllib),
uv of the managed_bootstrap version, and access to pypi.org and
download.pytorch.org:

    python scripts/build_runtime_package_hashes.py [--uv PATH]
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import unquote
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import install_managed_backend as installer  # noqa: E402

OUTPUT = ROOT/installer.PACKAGE_HASHES
PYPI = 'https://pypi.org/simple'
PYTORCH = 'https://download.pytorch.org/whl/{tag}'


def wheel_fits(filename, minor):
    """Windows x86-64 CPython 3.<minor> wheel tags, as pip would accept them."""
    parts = filename[:-len('.whl')].split('-')
    python_tags, abi_tags, platforms = (part.split('.') for part in parts[-3:])
    if not set(platforms) & {'any', 'win_amd64'}:
        return False
    for tag in python_tags:
        if tag == 'py3' or tag == f'cp3{minor}':
            return True
        if tag.startswith('py3') and tag[3:].isdigit() and int(tag[3:]) <= minor:
            return True
        if tag.startswith('cp3') and tag[3:].isdigit() and 'abi3' in abi_tags and int(tag[3:]) <= minor:
            return True
    return False


def moss_requirements(contract):
    project = tomllib.loads((ROOT/contract['sources']['moss']['path']/'pyproject.toml').read_text('utf8'))['project']
    return [*project['dependencies'], *project['optional-dependencies']['torch-runtime']]


def lock_environment(uv, work, role, models, tag, contract, settled, now):
    version = installer.role_python(role)
    minor = int(version.split('.')[1])
    pins = installer.role_pins(contract, role, models, tag)
    # Requirements keep their extras (nemo_toolkit[asr] pulls datasets, lhotse,
    # ...); constraints cannot carry extras, so they use the bare pins. Locking
    # the bare pins alone left the canary closure without the [asr] packages
    # and the mirror path unsatisfiable (found 2026-10-14).
    requirements = [f'{name}=={value}' for name, value in installer.role_packages(contract, role, models).items()]
    requirements += [pin for pin in pins if pin.startswith(('torch==', 'torchaudio=='))]
    extra = moss_requirements(contract) if role == 'moss' else []
    project = work/f'{role}-{version}-{tag}'
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    quoted = lambda items: '[' + ', '.join(json.dumps(item) for item in items) + ']'
    (project/'pyproject.toml').write_text(f'''[project]
name = "runtime-hash-lock"
version = "0"
requires-python = "=={version.rsplit('.', 1)[0]}.*"
dependencies = {quoted([*requirements, *extra])}

[tool.uv]
package = false
environments = ["sys_platform == 'win32' and platform_machine == 'AMD64'"]
constraint-dependencies = {quoted(pins)}

[[tool.uv.index]]
name = "pytorch"
url = "{PYTORCH.format(tag=tag)}"
explicit = true

[tool.uv.sources]
torch = {{ index = "pytorch" }}
torchaudio = {{ index = "pytorch" }}
''', 'utf8')
    env = dict(os.environ, UV_CACHE_DIR=str(work/'cache'), UV_PYTHON_DOWNLOADS='never')
    # Domestic mirrors lag PyPI by hours to days; unpinned dependencies use
    # releases that have settled. Exact pins are exempt (they are fixed anyway).
    exempt = [item for pin in pins for item in ('--exclude-newer-package', f"{pin.split('==')[0]}={now}")]
    subprocess.run([uv, 'lock', '--directory', str(project), '--default-index', PYPI,
                    '--python', version.rsplit('.', 1)[0], '--exclude-newer', settled, *exempt], check=True, env=env)
    lock = tomllib.loads((project/'uv.lock').read_text('utf8'))
    packages = {}
    sdist_only = []
    for package in lock['package']:
        registry = package.get('source', {}).get('registry')
        if registry is None:
            continue  # the virtual project itself
        if registry.rstrip('/') not in {PYPI, PYTORCH.format(tag=tag)}:
            raise RuntimeError(f"{package['name']} 来自未预期的索引 {registry}")
        name = installer.normalize(package['name'])
        files = [w for w in package.get('wheels', []) if wheel_fits(unquote(w['url'].rsplit('/', 1)[1]), minor)]
        if not files and package.get('sdist'):
            files = [package['sdist']]
            sdist_only.append(name)
        if not files:
            raise RuntimeError(f'{name} {package["version"]} 没有可用于 Windows/Python {version} 的文件')
        if name in packages and packages[name]['version'] != package['version']:
            raise RuntimeError(f'{name} 在同一环境出现两个版本，锁表需要单一版本')
        hashes = sorted({f['hash'].split(':', 1)[1] for f in files if f['hash'].startswith('sha256:')})
        packages[name] = {'version': package['version'], 'sha256': hashes}
    for pin in pins:
        name, _, value = pin.partition('==')
        if packages.get(installer.normalize(name), {}).get('version') != value:
            raise RuntimeError(f'{role}/{tag} 解析结果缺少锁定版本 {pin}')
    return f'{role}|{version}|{tag}', {'pins': pins, 'extra_requirements': extra,
                                       'sdist_only': sdist_only, 'packages': packages}


def build_backend(contract):
    """Official wheels for the pinned setuptools/wheel that source builds use."""
    backend = {}
    for name in ('setuptools', 'wheel'):
        version = contract['runtime'][name]
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as response:
            files = json.load(response)['urls']
        hashes = sorted(f['digests']['sha256'] for f in files if f['filename'].endswith('-py3-none-any.whl'))
        if not hashes:
            raise RuntimeError(f'{name} {version} 没有官方 wheel')
        backend[name] = {'version': version, 'sha256': hashes}
    return backend


def render(data):
    """One package per line keeps reviews and diffs readable."""
    lines = ['{']
    for key in ('schema', 'note', 'generated_at', 'unpinned_published_before', 'uv'):
        lines.append(f'  {json.dumps(key)}: {json.dumps(data[key], ensure_ascii=False)},')
    lines.append('  "build_backend": {')
    backend = sorted(data['build_backend'].items())
    for index, (name, item) in enumerate(backend):
        lines.append(f'    {json.dumps(name)}: {json.dumps(item, sort_keys=True)}' + (',' if index < len(backend) - 1 else ''))
    lines.append('  },')
    lines.append('  "environments": {')
    environments = sorted(data['environments'].items())
    for index, (key, entry) in enumerate(environments):
        lines.append(f'    {json.dumps(key)}: {{')
        for field in ('pins', 'extra_requirements', 'sdist_only'):
            lines.append(f'      {json.dumps(field)}: {json.dumps(entry[field])},')
        lines.append('      "packages": {')
        items = sorted(entry['packages'].items())
        for item_index, (name, item) in enumerate(items):
            comma = ',' if item_index < len(items) - 1 else ''
            lines.append(f'        {json.dumps(name)}: {json.dumps(item, sort_keys=True)}{comma}')
        lines.append('      }')
        lines.append('    }' + (',' if index < len(environments) - 1 else ''))
    lines.append('  }')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uv', default=shutil.which('uv') or 'uv')
    parser.add_argument('--work', type=Path, default=ROOT/'tmp/runtime-package-hashes')
    parser.add_argument('--settle-days', type=int, default=7,
                        help='unpinned dependencies must have been published at least this long ago')
    parser.add_argument('--roles', default='',
                        help='comma list: regenerate only these roles inside the existing table, '
                             'with its own cutoff and timestamps (other environments stay byte-identical)')
    args = parser.parse_args()
    now_time = datetime.now(timezone.utc)
    now = now_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    settled = (now_time - timedelta(days=args.settle_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    only = {role for role in args.roles.split(',') if role}
    existing = json.loads(OUTPUT.read_text('utf8')) if only else None
    if existing:
        now, settled = existing['generated_at'], existing['unpinned_published_before']
    contract = json.loads((ROOT/'dependencies.lock.json').read_text('utf-8-sig'))
    expected = contract['managed_bootstrap']['uv_version']
    actual = subprocess.run([args.uv, '--version'], capture_output=True, text=True, check=True).stdout.split()[1]
    if actual != expected:
        raise SystemExit(f'需要 uv {expected}（与运行库安装一致），当前是 {actual}')
    runtime = contract['runtime']
    tags = ['cpu', runtime['cuda_wheel'], runtime['cuda_wheel_modern']]
    environments = dict(existing['environments']) if existing else {}
    for role, models in installer.planned_roles(set(contract['models'])):
        if only and role not in only:
            continue
        for tag in tags:
            key, entry = lock_environment(args.uv, args.work, role, models, tag, contract, settled, now)
            environments[key] = entry
            print(f'{key}: {len(entry["packages"])} packages, sdist-only {entry["sdist_only"] or "none"}', flush=True)
    data = {'schema': 1,
            'note': 'Generated by scripts/build_runtime_package_hashes.py from pypi.org and download.pytorch.org. '
                    'Used only when the official source fails: a mirror file is accepted only if its SHA-256 is listed here.',
            'generated_at': now, 'unpinned_published_before': settled, 'uv': actual,
            'build_backend': existing['build_backend'] if existing else build_backend(contract),
            'environments': dict(sorted(environments.items()))}
    OUTPUT.write_bytes(render(data).encode('utf8'))
    print(f'wrote {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
