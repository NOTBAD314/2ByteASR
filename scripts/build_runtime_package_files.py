"""Regenerate scripts/runtime_package_files.json: where each locked package file lives on PyPI.

The runtimes install only files whose SHA-256 is locked (Windows:
scripts/runtime_package_hashes.json; macOS: packaging/macos/requirements-*.txt
and constraints-cpu.txt). This table adds, for every such file, its name, its
``packages/...`` path and its size, read from PyPI's own JSON API. PyPI and the
domestic mirrors (scripts/runtime_sources.json) serve a file at the same path,
so the installers can fetch it themselves from whichever source is fastest,
resume it on another source, check the SHA-256, and let uv / pip install
offline. Versions and hashes are never chosen here; a locked hash that PyPI
does not list fails the run.

macOS lists every Apple Silicon variant of a version (macOS 11 / 14 / 15 / 26
wheels differ for numpy, mlx, ...); the preparer picks with pip's own tag order
on the user's Mac.

Run after scripts/build_runtime_package_hashes.py or after changing the macOS
requirement files (needs access to pypi.org and the ``packaging`` library):

    python scripts/build_runtime_package_files.py
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'scripts/runtime_package_files.json'
HASHES = ROOT / 'scripts/runtime_package_hashes.json'
MACOS = ROOT / 'packaging/macos'
FILES_HOST = 'https://files.pythonhosted.org/'
# Newest macOS whose wheels a future Mac may pick; older variants are kept as well.
MACOS_NEWEST = (26, 0)
PIN = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s;\\]+)')
HASH = re.compile(r'--hash=sha256:([0-9a-f]{64})')
# (requirement files, constraint files, Python) per macOS runtime; requirement
# files are read with their -r / -c includes.
MACOS_ENVIRONMENTS = {
    'main|3.10': ('requirements-cpu.txt', (3, 10)),
    'moss|3.12': ('requirements-moss.txt', (3, 12)),
    'mlx|3.10': ('requirements-mlx.txt', (3, 10)),
}


def pypi_release(name, version, attempts=5):
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError:
            raise
        except (OSError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 + attempt * 3)


def file_row(item):
    url = item['url']
    if not url.startswith(FILES_HOST + 'packages/'):
        raise RuntimeError(f'unexpected PyPI file URL {url}')
    return [item['filename'], url[len(FILES_HOST):], int(item['size'])]


def read_requirements(path, seen=None):
    """{canonical name: (version, {sha256})} from a requirement file and its -r / -c includes."""
    seen = set() if seen is None else seen
    if path in seen:
        return {}
    seen.add(path)
    pins = {}
    current = None
    for raw in path.read_text('utf8').splitlines():
        line = raw.split(' #', 1)[0].strip() if not raw.lstrip().startswith('--hash') else raw.strip()
        if not line or line.startswith('#'):
            continue
        include = re.match(r'^-(r|c)\s+(\S+)', line)
        if include:
            for name, (version, hashes) in read_requirements(path.parent / include.group(2), seen).items():
                pins.setdefault(name, (version, set()))[1].update(hashes)
            continue
        match = PIN.match(line)
        if match:
            current = canonicalize_name(match.group(1))
            version = match.group(3)
            if current in pins and pins[current][0] != version:
                raise RuntimeError(f'{path.name}: {current} pinned to {pins[current][0]} and {version}')
            pins.setdefault(current, (version, set()))
        if current:
            pins[current][1].update(HASH.findall(line))
    return pins


def apple_silicon_tags(python):
    """Every tag some Apple Silicon Mac running ``python`` accepts (all macOS versions)."""
    platforms = list(mac_platforms(MACOS_NEWEST, 'arm64'))
    interpreter = f'cp{python[0]}{python[1]}'
    return {str(tag) for tag in [*cpython_tags(python, [interpreter], platforms),
                                 *compatible_tags(python, interpreter, platforms)]}


def macos_environment(key, requirement, python, bundled):
    pins = read_requirements(MACOS / requirement)
    accepted = apple_silicon_tags(python)
    packages, rows = {}, {}

    def one(item):
        name, (version, hashes) = item
        release = pypi_release(name, version)
        chosen = []
        for entry in release['urls']:
            if entry['packagetype'] != 'bdist_wheel':
                continue
            tags = {str(tag) for tag in parse_wheel_filename(entry['filename'])[3]}
            if not tags & accepted:
                continue
            digest = entry['digests']['sha256']
            if hashes and digest not in hashes:
                continue  # a hash-pinned requirement file decides which files are allowed
            chosen.append((digest, file_row(entry)))
        return name, version, chosen

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(one, sorted((n, p) for n, p in pins.items() if n not in bundled)))
    for name, version, chosen in results:
        if not chosen:
            raise RuntimeError(f'macOS {key}: PyPI has no Apple Silicon wheel for {name}=={version}')
        packages[name] = dict(version=version, sha256=sorted(digest for digest, _ in chosen))
        rows.update(chosen)
    return dict(python='.'.join(map(str, python)), packages=packages), rows


def windows_rows(table):
    wanted = {}
    for entry in table['environments'].values():
        for name, item in entry['packages'].items():
            if '+' in item['version']:
                continue  # PyTorch builds come from the PyTorch indexes (pytorch_sources)
            wanted.setdefault((name, item['version']), set()).update(item['sha256'])
    for name, item in table['build_backend'].items():
        wanted.setdefault((canonicalize_name(name), item['version']), set()).update(item['sha256'])
    rows = {}

    def one(key):
        name, version = key
        release = pypi_release(name, version)
        found = {entry['digests']['sha256']: file_row(entry) for entry in release['urls']
                 if entry['digests']['sha256'] in wanted[key]}
        missing = wanted[key] - set(found)
        if missing:
            raise RuntimeError(f'PyPI does not list {name}=={version} file(s) {sorted(missing)}')
        return found

    with ThreadPoolExecutor(8) as pool:
        for found in pool.map(one, sorted(wanted)):
            rows.update(found)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    table = json.loads(HASHES.read_text('utf8'))
    files = windows_rows(table)
    bundled = {canonicalize_name(item['name']) for item in
               json.loads((MACOS / 'source-wheels.lock.json').read_text('utf8'))['sources']}
    macos = {}
    for key, (requirement, python) in MACOS_ENVIRONMENTS.items():
        macos[key], rows = macos_environment(key, requirement, python, bundled)
        files.update(rows)
    payload = dict(
        schema=1,
        note=('Where each locked package file is published: [filename, path below files.pythonhosted.org / a '
              'mirror\'s pypi root, size]. Generated by scripts/build_runtime_package_files.py from PyPI\'s JSON '
              'API. Integrity still comes from the locked SHA-256 (the keys); this table only says where to fetch.'),
        generated_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        source_hashes=dict(windows='scripts/runtime_package_hashes.json',
                           macos=[f'packaging/macos/{name}' for name, _ in MACOS_ENVIRONMENTS.values()]),
        macos_bundled_source_wheels=sorted(bundled),
        macos=macos,
        files={digest: files[digest] for digest in sorted(files)},
    )
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
    # One file and one macOS package per line keeps diffs readable.
    text = re.sub(r'\[\n\s+("[^"\n]*"),\n\s+("[^"\n]*"),\n\s+(\d+)\n\s+\]', r'[\1, \2, \3]', text)
    text = re.sub(r'\[\n\s+("[0-9a-f]{64}"(?:,\n\s+"[0-9a-f]{64}")*)\n\s+\]',
                  lambda match: '[' + re.sub(r',\n\s+', ', ', match.group(1)) + ']', text)
    text = re.sub(r'\{\n\s+("version": "[^"\n]*"),\n\s+("sha256": \[[^\]\n]*\])\n\s+\}', r'{\1, \2}', text)
    args.output.write_text(text + '\n', encoding='utf8', newline='\n')
    print(f'{args.output}: {len(files)} files; macOS ' +
          ', '.join(f'{key} {len(value["packages"])} packages' for key, value in macos.items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
