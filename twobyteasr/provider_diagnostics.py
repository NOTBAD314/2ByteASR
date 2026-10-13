"""Credential-free CLI diagnostics shared by adapters and both UI surfaces."""
import re
from collections.abc import Mapping


def _model_configuration_failure(value):
    """Only error envelopes or the CLI's explicit model-selection error count."""
    import json
    error_texts = []
    def visit(item, error=False, depth=0):
        if depth > 8:
            return
        if isinstance(item, Mapping):
            result = item.get('result')
            rejected_result = (item.get('event') == 'result' and isinstance(result, Mapping)
                and result.get('status') not in {None, 'SUCCESS', 'success'})
            error = error or item.get('type') == 'error' or item.get('is_error') is True or rejected_result
            if not error and (item.get('type') in {'assistant', 'user', 'result'}
                    or item.get('role') in {'assistant', 'user'}
                    or item.get('event') == 'result'):
                # Model/user content may quote JSON-shaped errors. Successful
                # terminal envelopes are business output, never diagnostics.
                return
            for key, nested in item.items():
                if str(key).lower() not in _SECRET_KEYS:
                    visit(nested, error or str(key).lower() in {'error', 'errors'}, depth + 1)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested, error, depth + 1)
        elif isinstance(item, str):
            try:
                visit(json.loads(item), error, depth + 1)
            except (ValueError, TypeError):
                if len(item.splitlines()) > 1:
                    for line in item.splitlines():
                        visit(line, error, depth)
                    return
                if error or depth == 0 and re.match(r"(?is)^\s*(?:error:\s*)?couldn.t set model\b", item):
                    error_texts.append(item)
    visit(value)
    if not re.search(r'(?i)\bunknown model id\b', '\n'.join(error_texts)):
        return None
    return {'category': 'unknown_model', 'message':
            '服务端拒绝了当前模型 ID。请在 AI 设置中确认可用模型，修改后重试；本轮保留本地结果。',
            'details': public_stream_text(str(value))}


def cli_failure(value):
    """Read nested CLI envelopes without mistaking an error for model output.

    Version constraints are supplied by the server, never a pinned 'latest'.
    Keep the full credential-free envelope for the details/clipboard surface.
    """
    model_failure = _model_configuration_failure(value)
    if model_failure:
        return model_failure
    import json
    texts = []
    def visit(item, depth=0):
        if depth > 8:
            return
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if str(key).lower() not in _SECRET_KEYS:
                    if str(key).lower() in {'http_status', 'status', 'status_code'} and nested == 426:
                        texts.append('HTTP status 426')
                    if str(key).lower() in {'minimum_version', 'minimum_cli_version', 'required_version'}:
                        texts.append('minimum version ' + str(nested))
                    if str(key).lower() in {'cli_version', 'client_version', 'received_version'}:
                        texts.append('Grok CLI version ' + str(nested))
                    visit(nested, depth + 1)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested, depth + 1)
        elif isinstance(item, str):
            texts.append(item)
            try:
                visit(json.loads(item), depth + 1)
            except (ValueError, TypeError):
                start = item.find('{')
                if start >= 0:
                    try:
                        visit(json.JSONDecoder().raw_decode(item[start:])[0], depth + 1)
                    except ValueError:
                        pass
    visit(value)
    text = '\n'.join(texts)
    if not (re.search(r'(?i)(?:status|http(?:_status)?)\D{0,20}426\b', text)
            or re.search(r'(?i)\bupgrade required\b', text)):
        return None
    version = re.search(r'(?i)(?:Grok\s+CLI\s+version|client\s+version)\s*[:=( ]+([\w.+-]+)', text)
    minimum = re.search(r'(?i)(?:update\s+to\s+(?:version\s+)?|requires?\s+(?:at\s+least\s+|version\s+)?|minimum\s+(?:version\s*)?[:= ]*)(\d+(?:\.\d+)+(?:[-+][\w.]+)?)', text)
    received = version.group(1).rstrip(').,') if version else ''
    required = minimum.group(1) if minimum else ''
    description = 'Grok CLI 版本过旧。'
    if received:
        description += f'服务端收到 {received}，'
    if required:
        description += f'要求至少 {required}，'
    description += '请更新后重试。'
    return {'category': 'upgrade_required', 'http_status': 426,
            'received_version': received, 'minimum_version': required,
            'message': description, 'details': public_stream_text(str(value))}

_SECRET_KEYS={'token','cookie','password','secret','api_key','access_token','refresh_token','id_token','authorization'}
_PATTERNS=[
    re.compile(r'(?i)(https?://)[^/\s"\']+@'),
    re.compile(r'(?i)\bBearer\s+[^\s,"\']+'),
    re.compile(r'(?i)(?:access_token|refresh_token|id_token|api[_-]?key|authorization|cookie|password|token|secret)["\']?\s*[=:]\s*["\']?[^\s,"\';}&]+'),
    re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'),
    re.compile(r'\b(?:sk-|xai-|ghp_|glpat-|ya29\.|AIza|gsk_)[A-Za-z0-9._-]{10,}'),
    # Alibaba Cloud AccessKey IDs (RAM) and signed-URL credentials in queries.
    re.compile(r'\bLTAI[A-Za-z0-9]{12,}'),
    re.compile(r'(?i)(?:OSSAccessKeyId|Signature|x-oss-credential|x-oss-signature|X-Amz-Credential|X-Amz-Signature)=[^&\s"\']+'),
    # An unanchored leading + retries at every character in a large CLI
    # stderr line, blocking both drain callbacks for minutes. Only begin at
    # the start of an address token; redaction semantics stay unchanged.
    re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'),
    re.compile(r'\x1b\[[0-9;?]*[A-Za-z]'),
]

def redact_diagnostics(value, *, key=''):
    if key.lower() in {'thinking', 'reasoning_content', 'signature'}:
        return '[not retained]'
    if key.lower() in _SECRET_KEYS or any(k in key.lower() for k in ('access_token','refresh_token','api_key')):
        return '[REDACTED]'
    if isinstance(value,Mapping):return {str(k):redact_diagnostics(v,key=str(k)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [redact_diagnostics(v) for v in value]
    if isinstance(value,str):
        # stderr often embeds JSON as an escaped message inside outer JSON.
        # Decode complete objects (including an 'Internal error:' prefix) so
        # sensitive keys do not bypass redaction merely through extra slashes.
        import json
        start = value.find('{')
        if start >= 0:
            try:
                parsed, end = json.JSONDecoder().raw_decode(value[start:])
                if isinstance(parsed, (dict, list)):
                    value = value[:start] + json.dumps(redact_diagnostics(parsed), ensure_ascii=False) + value[start + end:]
            except (ValueError, TypeError):
                pass
        for pattern in _PATTERNS:value=pattern.sub('[REDACTED]',value)
    return value


def public_stream_text(text):
    """Redact parsed envelopes before slicing diagnostic tails."""
    import json
    rows=[]
    for line in str(text or '').splitlines():
        try:
            rows.append(json.dumps(redact_diagnostics(json.loads(line)),ensure_ascii=False))
        except ValueError:
            # A truncated private event must not fall back to its raw text.
            if re.search(r'"(?:thinking|reasoning_content|signature)"\s*:',line):
                rows.append('[incomplete private event omitted]')
            else:
                rows.append(redact_diagnostics(line))
    return '\n'.join(rows)

def command_phase(purpose):
    value=purpose.lower()
    if 'version' in value or 'installation' in value:return '可执行文件与版本'
    if 'models' in value:return '模型列表'
    if 'readiness' in value:return '会话真实请求'
    if 'status' in value:return '登录状态'
    return '模型请求'


def collect_search_evidence(packet, evidence):
    """Only completed tool-result envelopes count, never assistant prose."""
    if not isinstance(packet,dict):
        return
    message=packet.get('message') or {}
    blocks=message.get('content',[]) if isinstance(message,dict) else []
    inner=packet.get('event') if packet.get('type')=='stream_event' else None
    if isinstance(inner,dict) and inner.get('type')=='content_block_start':
        block=inner.get('content_block')
        if isinstance(block,dict):blocks=[*blocks,block]
    for block in blocks if isinstance(blocks,list) else []:
        if not isinstance(block,dict):
            continue
        if block.get('type')=='web_search_tool_result' and isinstance(block.get('content'),list):
            urls=[x['url'] for x in block['content'] if isinstance(x,dict) and
                  x.get('type')=='web_search_result' and str(x.get('url','')).startswith('https://')]
            if urls:
                key=str(block.get('tool_use_id',''))
                if not any(row.get('tool_use_id')==key for row in evidence):
                    evidence.append({'tool':'web_search','tool_use_id':key,'urls':list(dict.fromkeys(urls)),
                        'results':[{'url':x['url'],'title':str(x.get('title',''))[:300]} for x in block['content']
                                   if isinstance(x,dict) and x.get('type')=='web_search_result' and x.get('url') in urls]})
    step=packet.get('step_update') or {}
    if (packet.get('event')=='step_update' and step.get('state')=='DONE'
            and step.get('step_type')=='tool' and step.get('tool_name') in {'search_web','web_search'}):
        info=step.get('tool_info') or {}
        if not info.get('error'):
            # A completed search-tool step is itself proof the search ran, even
            # when the stream omits the output body (agy step_updates carry no
            # tool output; URLs then come from the structured reply + spot fetch).
            evidence.append({'tool':step['tool_name'],'step_index':step.get('step_index'),
                'urls':list(dict.fromkeys(re.findall(r'https://[^\s<>"\\]+',str(info.get('output') or ''))))})


def diagnostic_phases(trace):
    """Seven measured phases. Missing work is explicit, never reported as zero latency."""
    history = list(trace.get('process_history') or [])
    timings = trace.get('timings') or {}
    def process_phase(label, match):
        row = next((r for r in reversed(history) if match(str(r.get('purpose', '')).lower())), None)
        return {'phase': label, 'state': 'measured' if row else 'not_run',
                'seconds': (row.get('timings') or {}).get('process_seconds') if row else None,
                'exit_code': row.get('exit_code') if row else None,
                'stdout': row.get('stdout', '') if row else '', 'stderr': row.get('stderr', '') if row else ''}
    def timing_phase(label, name):
        value = timings.get(name)
        return {'phase': label, 'state': 'measured' if value is not None else 'not_run',
                'seconds': value, 'exit_code': trace.get('exit_code'),
                'stdout': trace.get('stdout', ''), 'stderr': trace.get('stderr', '')}
    return [process_phase('可执行文件发现与版本', lambda p:'version' in p or 'installation' in p),
            timing_phase('进程启动', 'spawn_seconds'),
            process_phase('登录/session 检查', lambda p:'readiness' in p or 'login status' in p),
            process_phase('模型列表', lambda p:'models' in p),
            timing_phase('首字节', 'first_stdout_seconds'),
            timing_phase('完整模型响应', 'process_seconds'),
            {**timing_phase('JSON/schema 校验', 'schema_parse_seconds'), 'schema_error': trace.get('schema_error', '')}]
