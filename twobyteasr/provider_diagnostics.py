"""Credential-free CLI diagnostics shared by adapters and both UI surfaces."""
import re
from collections.abc import Mapping

_SECRET_KEYS={'token','cookie','password','secret','api_key','access_token','refresh_token','id_token','authorization'}
_PATTERNS=[
    re.compile(r'(?i)(https?://)[^/\s"\']+@'),
    re.compile(r'(?i)\bBearer\s+[^\s,"\']+'),
    re.compile(r'(?i)(?:access_token|refresh_token|id_token|api[_-]?key|authorization|cookie|password|token|secret)["\']?\s*[=:]\s*["\']?[^\s,"\';}&]+'),
    re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'),
    re.compile(r'\b(?:sk-|xai-|ghp_|glpat-|ya29\.|AIza)[A-Za-z0-9._-]{10,}'),
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
