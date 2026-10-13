"""Small, credential-free helpers shared by the downloader and its diagnostics."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


def public_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if parsed.port:
            host += ':' + str(parsed.port)
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except ValueError:
        return '[invalid URL]'


def redact(value):
    if isinstance(value, dict):
        return {k: ('[redacted]' if any(s in k.lower() for s in ('token', 'cookie', 'password', 'authorization', 'secret'))
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'https?://[^\s\"\'<>]+', lambda m: public_url(m.group()), value)
        # requests can embed a relative URL in an exception, without a scheme.
        value = re.sub(r'(?i)(with url:\s*[^\s?]+)\?[^\s)]+', r'\1?[redacted]', value)
        value = re.sub(r'(?i)\b(?:Bearer\s+|(?:token|password|cookie|authorization)\s*[=:]\s*)[^\s,;]+', '[redacted]', value)
    return value


def category(exc) -> str:
    import requests
    if getattr(exc, 'download_category', ''):
        return exc.download_category
    if isinstance(exc, PermissionError):
        return 'permission'
    if isinstance(exc, requests.exceptions.SSLError):
        return 'tls_certificate'
    if isinstance(exc, requests.exceptions.ProxyError):
        return 'proxy'
    if isinstance(exc, requests.exceptions.Timeout):
        return 'network_timeout'
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    if status in (401, 403):
        return 'http_access'
    if status == 404:
        return 'source_unavailable'
    if status == 429:
        return 'rate_limited'
    if status and status >= 500:
        return 'connection'
    text = str(exc).lower()
    if 'network_timeout' in text:
        return 'network_timeout'
    if '磁盘空间不足' in text or 'no space' in text or 'disk full' in text:
        return 'disk_space'
    if 'sha-256' in text or '校验' in text:
        return 'checksum'
    if any(x in text for x in ('html', 'lfs 指针', 'content-range', '范围', '长度', '大小不正确')):
        return 'invalid_response'
    if isinstance(exc, requests.exceptions.ConnectionError):
        return 'dns' if 'name' in type(getattr(exc, '__cause__', None)).__name__.lower() or 'getaddrinfo' in text or 'name resolution' in text else 'connection'
    if isinstance(exc, requests.exceptions.ChunkedEncodingError) or 'incompleteread' in text:
        return 'connection'
    return 'unknown'


def retryable(exc) -> bool:
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    return status not in (400, 401, 403, 404, 416) and category(exc) not in ('permission', 'disk_space', 'tls_certificate', 'invalid_response')


class AnonymousAuth:
    """Prevent requests from silently borrowing an account's .netrc credentials."""
    def __call__(self, request):
        return request


def require_isolated_download_path(path):
    """Cheap child-process guard, before the first socket or file creation."""
    import os
    import json
    from pathlib import Path
    value = os.environ.get('TWOBYTEASR_TEST_ROOT')
    if not value:
        return
    root = Path(value).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(root):
        raise ValueError('隔离下载目标越界，已中止：' + str(target))
    fields = dict(pid=os.getpid(), root=str(root), destination=str(target))
    for key in ('2BYTEASR_MODEL_ROOT', 'LOCALAPPDATA', 'TEMP', 'HF_HOME', 'HF_HUB_CACHE', 'HF_XET_CACHE', 'MODELSCOPE_CACHE', 'TORCH_HOME'):
        if os.environ.get(key):
            item = Path(os.environ[key]).resolve()
            if not item.is_relative_to(root): raise ValueError('隔离缓存路径越界：' + key)
            fields[key] = str(item)
    print('[2BYTEASR_ISOLATION] ' + json.dumps(fields, ensure_ascii=False), flush=True)
