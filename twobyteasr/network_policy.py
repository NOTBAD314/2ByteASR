"""Application HTTP CA resolution and credential-free transport diagnostics.

No global patch, trust downgrade, retry, or certificate installation. Explicit
CA environment values take precedence over the packaged certifi bundle.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import ssl
import sys
import uuid
from urllib.parse import urlsplit

import certifi
import requests


class NetworkTrustError(requests.exceptions.SSLError):
    def __init__(self, message, *, category='tls_certificate', diagnostics=None):
        super().__init__(message)
        self.category = category
        self.diagnostics = diagnostics or {}


def ca_bundle():
    for name in ('REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
        value = os.environ.get(name)
        if value:
            path = Path(value).expanduser().resolve()
            if not path.exists() or not os.access(path, os.R_OK):
                raise NetworkTrustError(f'{name} 指向的证书路径不存在或不可读；请求未发送。', category='tls_ca_path')
            return str(path), name
    path = Path(certifi.where())
    if not path.is_file() or not os.access(path, os.R_OK):
        # Frozen resources resolve against the package, never the working dir.
        packaged = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'certifi' / 'cacert.pem'
        if not packaged.is_file():
            raise NetworkTrustError('应用 CA 文件缺失；请检查完整候选目录。请求未发送。', category='tls_ca_path')
        path = packaged
    return str(path.resolve()), 'certifi'


def public_url(value):
    try:
        p = urlsplit(str(value))
        return f'{p.scheme}://{p.hostname or ""}' + (f':{p.port}' if p.port else '') + p.path
    except ValueError:
        return '[invalid URL configuration]'


def terminal_category(message):
    value = str(message).casefold()
    if any(x in value for x in ('certificate_verify_failed','unable to get local issuer','self signed certificate','certificate has expired')):
        return 'tls_certificate'
    if any(x in value for x in ('authentication failed','invalid api key','unauthorized','not logged in')):
        return 'authentication_required'
    if any(x in value for x in ('unknown option','unknown tool','unsupported tool','model not found')):
        return 'unsupported_capability'
    return ''


def snapshot():
    import importlib.metadata
    versions = {}
    for name in ('requests', 'urllib3', 'httpx', 'certifi'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'metadata unavailable'
    try:
        path, source = ca_bundle()
        p = Path(path)
        ca = dict(path=path, source=source, exists=p.exists(), readable=os.access(p, os.R_OK),
                  sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    except NetworkTrustError as exc:
        ca = dict(error=str(exc), category=exc.category)
    proxies = requests.utils.get_environ_proxies('https://api.deepseek.com')
    return dict(python=sys.version.split()[0], openssl=ssl.OPENSSL_VERSION, versions=versions,
        executable=sys.executable, frozen=bool(getattr(sys, 'frozen', False)),
        meipass=str(getattr(sys, '_MEIPASS', '')), cwd=os.getcwd(), certifi_module=certifi.__file__, ca=ca,
        proxy={k: public_url(v) if k != 'no' else '[configured]' for k,v in proxies.items()},
        ca_environment={k:os.environ.get(k) for k in ('SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE')},
        policy='explicit CA > packaged certifi; hostname and chain verification required')


def request(method, url, **kwargs):
    from .provider_diagnostics import redact_diagnostics
    request_id = uuid.uuid4().hex
    path, source = ca_bundle()
    if kwargs.get('verify') is False:
        raise NetworkTrustError('应用请求必须验证 HTTPS 证书。', category='tls_configuration')
    kwargs.setdefault('verify', path)
    try:
        return getattr(requests, method.lower())(url, **kwargs)
    except requests.exceptions.SSLError as exc:
        diagnostics = snapshot()
        diagnostics.update(request_id=request_id, target=public_url(url), stage='tls_handshake',
                           client='requests', detail=redact_diagnostics(str(exc)))
        from .runtime_paths import user_data_root
        import json
        dest = user_data_root() / 'SubtitleStudioPreview' / 'logs' / 'network'
        try:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / (request_id+'.json')).write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),encoding='utf8')
        except OSError:
            pass
        raise NetworkTrustError('HTTPS 证书校验失败；模型列表与生成均可能受影响。请查看网络诊断后重试。'
                                f'（诊断 {request_id}）', diagnostics=diagnostics) from exc


def get(url, **kwargs):
    return request('get', url, **kwargs)


def post(url, **kwargs):
    return request('post', url, **kwargs)
