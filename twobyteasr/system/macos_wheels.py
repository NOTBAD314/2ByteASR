"""Verified, bundled wheels for packages PyPI publishes only as source.

The end-user installer never invokes a compiler or downloads a source archive.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

WHEELHOUSE = 'wheels/macos-arm64-cp310'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_wheel(path: Path) -> list[dict]:
    from scripts.macos_binary_audit import MAGICS,parse_macho,version
    native=[]
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith('/'):continue
            with archive.open(name) as stream:magic=stream.read(4)
            if magic not in MAGICS:continue
            slices=parse_macho(archive.read(name))
            selected=[s for s in slices if s['architecture']=='arm64']
            if not selected or any(not s['minimum_macos'] or version(s['minimum_macos'])>version('14.0') for s in selected):
                raise RuntimeError('Bundled wheel exceeds native target: '+name)
            for item in selected:
                for link in item['linked']:
                    if link['path'].startswith('/') and not link['path'].startswith(('/System/Library/','/usr/lib/')):
                        raise RuntimeError('Bundled wheel has a build-host dependency: '+name)
            native.append(dict(path=name,slices=slices))
    return native


def verify_wheelhouse(root: Path, *, directory: Path | None = None) -> Path:
    folder=directory or root/WHEELHOUSE
    lock_path=root/'packaging/macos/source-wheels.lock.json'
    try:
        lock=json.loads(lock_path.read_text('utf8'))
        record=json.loads((folder/'manifest.json').read_text('utf8'))
    except (OSError,ValueError) as exc:
        raise RuntimeError('Mac 程序包缺少或损坏预编译依赖缓存；请重新安装相容版，不需要自行安装开发工具。') from exc
    if record.get('source_lock_sha256')!=digest(lock_path) or record.get('target')!='darwin-arm64-cp310':
        raise RuntimeError('Bundled Mac wheelhouse source/architecture differs')
    expected={(r['name'].lower().replace('_','-'),r['version']):r['sha256'] for r in lock['sources']}
    rows=record.get('wheels',[])
    actual={}
    for row in rows:
        key=(row['package'].lower().replace('_','-'),row['version'])
        name=row['file']
        if key in actual or Path(name).name!=name or '/' in name or '\\' in name or not name.endswith('.whl'):
            raise RuntimeError('Invalid or duplicate Mac wheelhouse member')
        if row.get('source_sha256')!=expected.get(key) or digest(folder/name)!=row['sha256']:
            raise RuntimeError('Bundled Mac wheel checksum differs: '+name)
        inspect_wheel(folder/name)
        actual[key]=row['source_sha256']
    if actual!=expected:raise RuntimeError('Bundled Mac wheelhouse is incomplete')
    return folder
