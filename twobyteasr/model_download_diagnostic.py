"""Explicit, bounded model download self-check. Never installs or uploads."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

from .download_diagnostics import public_url, redact, category
from .repository_download import planned_sources, _artifact_url

PROBE_BYTES = 64 * 1024


def load_http_client(root):
    path = Path(root) / 'scripts/download_file_fast.py'
    spec = importlib.util.spec_from_file_location('twobyte_model_probe_http', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def network_facts():
    """No IPs, tokens, proxy URLs or user configuration contents are retained."""
    import requests
    import importlib.metadata
    result = dict(python=sys.version.split()[0], backend='requests',
        proxy_environment={k: bool(os.environ.get(k)) for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY')},
        offline_flags={k: os.environ.get(k,'') for k in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE')},
        credentials='public anonymous requests; no netrc or implicit HF token',
        mainland_direct='UNVERIFIED: application proxy settings cannot exclude global/TUN routing')
    result['versions'] = {}
    for name in ('requests', 'urllib3', 'certifi', 'huggingface-hub', 'modelscope'):
        try: result['versions'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    result['effective_requests_proxy_present'] = bool(requests.utils.get_environ_proxies('https://modelscope.cn'))
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
                try: result['system_proxy_enabled'] = bool(winreg.QueryValueEx(key, 'ProxyEnable')[0])
                except OSError: result['system_proxy_enabled'] = False
                try: result['system_pac_present'] = bool(winreg.QueryValueEx(key, 'AutoConfigURL')[0])
                except OSError: result['system_pac_present'] = False
        except OSError: result['system_proxy_read'] = 'unavailable'
    return result


def bounded_probe(client, url, filename, *, limit=PROBE_BYTES, metadata=False):
    if not 1 <= limit <= PROBE_BYTES:
        raise ValueError('Probe must stay within 64 KiB')
    started = time.monotonic()
    result = dict(host=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(url).hostname,
                  file=filename, body_limit=limit, status='FAIL', scope='reachability only; not a full download')
    try:
        with client._session() as session:
            with session.get(url, headers={'Range':f'bytes=0-{limit-1}'},stream=True,timeout=(8,12)) as response:
                result.update(http_status=response.status_code, headers_s=round(time.monotonic()-started,3),
                    redirect_hosts=[__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(r.url).hostname for r in [*response.history,response]],
                    content_range=response.headers.get('Content-Range',''),content_type=response.headers.get('Content-Type',''))
                if metadata:
                    response.raise_for_status()
                else:
                    client._validate_download_response(response, filename)
                if response.status_code == 206 or response.headers.get('Content-Range'):
                    match = client.CONTENT_RANGE.fullmatch(response.headers.get('Content-Range', '').strip())
                    if not match or int(match[1]) != 0 or int(match[2]) >= limit:
                        raise RuntimeError('Content-Range 与受限探测请求不一致')
                # read(size) is bounded even if the server ignores Range or lies
                # about Content-Length. Close immediately after this prefix.
                body = response.raw.read(limit, decode_content=False)
                if not metadata:
                    client._validate_body_prefix(body)
                if not body: raise RuntimeError('来源返回空文件')
                result.update(status='PASS',consumed_bytes=len(body),prefix_sha256=hashlib.sha256(body).hexdigest())
                if filename.endswith('.json') and len(body) < limit:
                    json.loads(body)
                    result['json_valid'] = True
    except Exception as exc:
        result.update(status='FAIL',category=category(exc),detail=redact(str(exc)))
    result['elapsed_s'] = round(time.monotonic()-started,3)
    return result


def bootstrap_probes(lock, root=None):
    """The common pre-weight chain uses curl/uv; report that distinction.

    Official sources first, then the first domestic fallback of each kind that
    the installer tries next (scripts/runtime_sources.json)."""
    sources = {}
    if root is not None and (Path(root)/'scripts/runtime_sources.json').is_file():
        sources = json.loads((Path(root)/'scripts/runtime_sources.json').read_text('utf-8'))
    archive = sources.get('python_probe_archive', '')
    probes = [
        ('uv 工具', lock['managed_bootstrap']['uv_url'], 'uv-windows.zip', False),
        *([('Python 安装包', sources['python_official']+'/'+archive, 'python.tar.gz', False)]
          if archive and sources.get('python_official') else
          [('Python 发布元数据', 'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest', 'python-release.json', True)]),
        ('PyTorch CUDA 包索引', 'https://download.pytorch.org/whl/cu128/torch/', 'torch-index', True),
        ('PyPI 包索引', 'https://pypi.org/simple/requests/', 'requests-index', True),
    ]
    domestic_uv = next((item for item in sources.get('uv', {}).get('fallbacks', []) if 'PyPI 镜像' in item['label']), None)
    if domestic_uv:
        probes.append((f"uv 工具（{domestic_uv['label']}）", domestic_uv['url'], 'uv.whl', False))
    if archive and sources.get('python_mirrors'):
        mirror = sources['python_mirrors'][0]
        probes.append((f"Python 安装包（{mirror['label']}）", mirror['url']+'/'+archive, 'python.tar.gz', False))
    if sources.get('pytorch_mirrors'):
        mirror = sources['pytorch_mirrors'][0]
        probes.append((f"PyTorch 包索引（{mirror['label']}）", mirror['url'].format(tag='cu128')+'/torch/', 'torch-index', True))
    if sources.get('pypi_mirrors'):
        mirror = sources['pypi_mirrors'][0]
        probes.append((f"PyPI 包索引（{mirror['label']}）", mirror['url']+'/requests/', 'requests-index', True))
    return probes


def check_downloads(root: Path, model_root: Path, keys, mode='AUTO', *, notify=None, cancel=None):
    root, model_root = Path(root), Path(model_root)
    lock = json.loads((root/'dependencies.lock.json').read_text('utf-8-sig'))
    keys = list(dict.fromkeys(keys or lock['models']))
    if any(k not in lock['models'] for k in keys): raise ValueError('未知模型')
    client = load_http_client(root)
    from .download_diagnostics import require_isolated_download_path
    require_isolated_download_path(model_root)
    result = dict(schema_version=1, started_at=datetime.now(timezone.utc).isoformat(),network=network_facts(),
                  mode=mode, models=[], bootstrap=[], complete_download=False, upload=False, total_consumed_bytes=0)
    try:
        model_root.mkdir(parents=True,exist_ok=True)
        marker=model_root/('.download-write-check-'+uuid.uuid4().hex)
        with marker.open('xb') as stream: stream.write(b'2ByteASR diagnostic')
        marker.unlink()
        result['disk']=dict(writable=True,free_bytes=shutil.disk_usage(model_root).free)
    except OSError as exc: result['disk']=dict(writable=False,category=category(exc),detail=redact(str(exc)))
    for stage, url, filename, metadata in bootstrap_probes(lock, root):
        if cancel and cancel.is_set(): result['cancelled']=True;break
        probe=bounded_probe(client,url,filename,metadata=metadata)
        probe.update(stage=stage,scope='requests reachability only; actual runtime installer uses curl/uv with system certificates')
        result['bootstrap'].append(probe)
        result['total_consumed_bytes']+=probe.get('consumed_bytes',0)
        if notify: notify('runtime','OFFICIAL',probe)
    for key in keys:
        if cancel and cancel.is_set(): result['cancelled']=True;break
        spec=lock['models'][key]
        model=dict(key=key,repo=spec['repository'],revision=spec['revision'],declared_bytes=spec.get('download_bytes'),sources=[])
        result['models'].append(model)
        for manifest in planned_sources(spec,mode):
            if cancel and cancel.is_set(): result['cancelled']=True;break
            row=dict(mode=manifest.mode,repository=manifest.repository,revision=manifest.revision,probes=[])
            model['sources'].append(row)
            config=next((f for f in manifest.files if f.endswith(('config.json','config.yaml','configuration.json'))),manifest.files[0])
            weight=next((f for f in manifest.files if f.endswith(('.safetensors','.pt','.bin','.tar','.nemo','.ckpt'))),None)
            for filename in dict.fromkeys([config,*([weight] if weight else [])]):
                if cancel and cancel.is_set(): result['cancelled']=True;break
                probe=bounded_probe(client,_artifact_url(manifest,filename),filename)
                row['probes'].append(probe)
                result['total_consumed_bytes']+=probe.get('consumed_bytes',0)
                if notify: notify(key,manifest.mode,probe)
    return redact(result)


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description='轻量模型下载检查：每个来源最多读取两个 64 KiB 前缀，不安装、不上传')
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--models',default='')
    p.add_argument('--mode',default='AUTO',choices=['AUTO','MODELSCOPE','HF_OFFICIAL','HF_MIRROR'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-network',action='store_true')
    args=p.parse_args(argv)
    if not args.allow_network: p.error('真实网络检查需要显式 --allow-network')
    from .runtime_paths import get_runtime_paths
    report=check_downloads(args.root,get_runtime_paths().model_root,args.models.split(',') if args.models else [],args.mode)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(str(args.output))
    return 0
