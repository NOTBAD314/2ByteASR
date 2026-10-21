"""Turn whatever a user pastes into exact cloud API addresses.

Four different things are kept apart everywhere in the setup UI:

* 官方网站 / 控制台网址 — where the user signs in (never called by the app);
* API Host — the host name only, e.g. ``llm-xxx.cn-beijing.maas.aliyuncs.com``;
* Base URL — the API root the app appends paths to, e.g. ``https://<host>/api/v1``;
* 完整请求 Endpoint — one concrete request URL, e.g. ``<Base URL>/services/audio/asr/transcription``.

Sources for Alibaba Cloud Model Studio (百炼), checked 2026-10-13:
https://help.aliyun.com/zh/model-studio/regions (workspace domain
``{WorkspaceId}.{region}.maas.aliyuncs.com``; keys and domains are per region
and cannot be mixed; the old ``dashscope.aliyuncs.com`` domain stays for
existing use and gets no new features after 2026-09-30) and
https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference (submit
``/api/v1/services/audio/asr/transcription``, query ``/api/v1/tasks/{task_id}``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

FILETRANS_PATH = '/services/audio/asr/transcription'
TASK_PATH = '/tasks/{task_id}'

DASHSCOPE_REGIONS = {
    'cn-beijing': '华北2（北京）',
    'ap-southeast-1': '新加坡',
    'cn-hongkong': '中国香港',
    'us-east-1': '美国（弗吉尼亚）',
    'eu-central-1': '德国（法兰克福）',
    'ap-northeast-1': '日本（东京）',
}
# Qwen Cloud (official international Qwen API, 2026-10-13): pay-as-you-go keys
# from home.qwencloud.com. Not a legacy domain and has no workspace id.
QWEN_CLOUD_HOSTS = {'maas.qwencloudapi.com': 'ap-southeast-1'}
# Legacy shared domains (no workspace id) and the region each belongs to.
LEGACY_DASHSCOPE_HOSTS = {
    'dashscope.aliyuncs.com': 'cn-beijing',
    'dashscope-intl.aliyuncs.com': 'ap-southeast-1',
    'cn-hongkong.dashscope.aliyuncs.com': 'cn-hongkong',
    'dashscope-us.aliyuncs.com': 'us-east-1',
}
_WORKSPACE_HOST = re.compile(r'^(?P<workspace>[a-z0-9][a-z0-9-]*)\.(?P<region>[a-z]{2}-[a-z]+-?\d*)\.maas\.aliyuncs\.com$')
_WORKSPACE_ID = re.compile(r'^llm-[a-z0-9]+$')


class EndpointInputError(ValueError):
    """The pasted text cannot be turned into a valid address; message is user-facing."""


@dataclass(frozen=True)
class DashScopeAddress:
    host: str
    region: str
    workspace_id: str
    legacy: bool
    qwen_cloud: bool = False

    @property
    def region_label(self) -> str:
        return DASHSCOPE_REGIONS.get(self.region, self.region or '未知地域')

    @property
    def base_url(self) -> str:
        """DashScope native API root (Base URL)."""
        return f'https://{self.host}/api/v1'

    @property
    def filetrans_url(self) -> str:
        return self.base_url + FILETRANS_PATH

    def task_url(self, task_id: str) -> str:
        return self.base_url + TASK_PATH.format(task_id=task_id)

    @property
    def compatible_base_url(self) -> str:
        """OpenAI-compatible root for chat models (never for 录音文件识别)."""
        return f'https://{self.host}/compatible-mode/v1'

    def notes(self) -> list[str]:
        notes = []
        if self.qwen_cloud:
            return ['Qwen Cloud（Qwen 官方国际站，新加坡）：用 Qwen Cloud 控制台创建的按量付费 API Key；'
                    '阿里云百炼（中国站）的 Key 不能在这里使用，反之亦然。']
        if self.legacy:
            notes.append('这是百炼旧的共用域名：仍可使用，但官方说明自 2026-09-30 起不再支持新特性；'
                         '建议改贴控制台“API Host”里的工作空间专属域名。')
        if self.region and self.region != 'cn-beijing':
            notes.append(f'地域：{self.region_label}。API Key 必须是同一地域创建的，不能跨地域混用。')
        return notes


def _host_and_path(value: str) -> tuple[str, str]:
    text = str(value or '').strip().strip('"\'')
    if not text:
        raise EndpointInputError('请先贴入百炼控制台里的 API Host。')
    if '://' not in text:
        text = 'https://' + text
    parts = urlsplit(text)
    if parts.username or parts.password:
        raise EndpointInputError('地址里不能包含用户名或密码。')
    if parts.scheme not in {'https', 'http'}:
        raise EndpointInputError('只支持 https 地址。')
    host = (parts.hostname or '').lower().rstrip('.')
    if not host:
        raise EndpointInputError('没有找到主机名。')
    return host, parts.path or ''


def parse_dashscope_address(value: str, *, region: str = '') -> DashScopeAddress:
    """Accept an API Host, Base URL, full endpoint, legacy domain or a bare Workspace ID."""
    text = str(value or '').strip()
    if _WORKSPACE_ID.match(text.lower()):
        if region not in DASHSCOPE_REGIONS:
            raise EndpointInputError('只填了 Workspace ID，还需要选择地域；或直接贴入完整的 API Host。')
        return DashScopeAddress(f'{text.lower()}.{region}.maas.aliyuncs.com', region, text.lower(), False)
    host, path = _host_and_path(text)
    if host in QWEN_CLOUD_HOSTS:
        return DashScopeAddress(host, QWEN_CLOUD_HOSTS[host], '', False, True)
    if host in LEGACY_DASHSCOPE_HOSTS:
        return DashScopeAddress(host, LEGACY_DASHSCOPE_HOSTS[host], '', True)
    match = _WORKSPACE_HOST.match(host)
    if match:
        found_region = match.group('region')
        if found_region not in DASHSCOPE_REGIONS:
            raise EndpointInputError(f'无法识别地域“{found_region}”。请从百炼控制台重新复制 API Host。')
        return DashScopeAddress(host, found_region, match.group('workspace'), False)
    if host.endswith('.aliyuncs.com'):
        raise EndpointInputError('这不是百炼模型服务的 API Host（应形如 llm-xxxx.cn-beijing.maas.aliyuncs.com）。'
                                 'OSS 存储地址请填在“OSS 存储”一栏。')
    if host.endswith('aliyun.com'):
        raise EndpointInputError('这是阿里云网站或控制台网址，不是 API Host。请在控制台的“API Host”处复制。')
    raise EndpointInputError('无法识别为百炼地址。请从百炼控制台复制“API Host”。')


def filetrans_endpoint(value: str, *, region: str = '') -> str:
    return parse_dashscope_address(value, region=region).filetrans_url


def describe_dashscope(value: str, *, region: str = '') -> dict:
    """All four address kinds for display in the setup dialog."""
    address = parse_dashscope_address(value, region=region)
    website = 'https://home.qwencloud.com/' if address.qwen_cloud else 'https://bailian.console.aliyun.com/'
    return {'website': website, 'api_host': address.host,
            'base_url': address.base_url, 'endpoint': address.filetrans_url,
            'task_url_example': address.task_url('<task_id>'), 'region': address.region,
            'region_label': address.region_label, 'workspace_id': address.workspace_id,
            'legacy': address.legacy, 'notes': address.notes()}


def describe_mosi(value: str = '') -> dict:
    from .mosi_asr import WEBSITE, normalize_api_base, transcriptions_url
    try:
        base = normalize_api_base(value)
    except ValueError as exc:
        raise EndpointInputError(str(exc)) from None
    return {'website': WEBSITE, 'api_host': urlsplit(base).hostname or '', 'base_url': base,
            'endpoint': transcriptions_url(base), 'task_url_example': base + '/audio/tasks/<task_id>',
            'notes': []}
