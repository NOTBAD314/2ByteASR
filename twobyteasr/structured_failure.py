"""Bounded diagnostics and explicit local JSON closure recovery, never success."""
import hashlib
import json
import re
import jsonschema


def diagnose(text, schema, errors=None):
    result = dict(stage='native_structured_output', characters=len(text),
                  utf8_bytes=len(text.encode('utf8')), issues=[], summary='')
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        byte_offset = len(text[:exc.pos].encode('utf8'))
        result.update(validator='json_syntax', character_offset=exc.pos, utf8_byte_offset=byte_offset,
                      line=exc.lineno, column=exc.colno)
        result['summary'] = f'JSON 语法错误：{exc.msg}；第 {exc.lineno} 行，第 {exc.colno} 字符列（UTF-8 字节偏移 {byte_offset}）'
    else:
        for exc in jsonschema.Draft202012Validator(schema).iter_errors(value):
            path = '$' + ''.join(f'[{p}]' if isinstance(p,int) else '.'+p for p in exc.path)
            issue = dict(path=path, validator=exc.validator)
            if exc.validator in {'minLength','maxLength','minItems','maxItems'}:
                issue.update(actual=len(exc.instance), limit=exc.validator_value)
            result['issues'].append(issue)
            if len(result['issues']) >= 5: break
        result['summary'] = '；'.join(f"{e['path']}: {e['validator']}" + (f"，实际 {e['actual']} / 限值 {e['limit']}" if 'actual' in e else '') for e in result['issues'])
    # Retain provider's short parser diagnosis, not an echoed HTML body.
    raw = str(errors or '')
    match = re.search(r'model output was not valid JSON:[^\r\n]{0,160}', raw)
    if match: result['provider_error'] = match.group(0)[:180]
    if not result['summary']:
        result['summary'] = '提供商结构校验未通过；当前本地契约未定位字段，原始失败终态已保留'
    return result


def recover_terminal_closure(text, schema):
    """Only append one missing object/array delimiter to a complete message.

    Caller MUST establish a complete assistant message + failed terminal. This
    helper does not accept streaming fragments, fix strings or rewrite values.
    """
    if len(text.encode('utf8')) > 1024*1024:
        raise ValueError('完整响应超过本地恢复边界')
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        # A closing delimiter of an outer container can expose a missing inner
        # object closer. Insert exactly one delimiter at the reported location.
        possibilities = []
        for pos in range(max(0,len(text.rstrip())-8), len(text.rstrip())+1):
            if not re.fullmatch(r'[\]\}\s]*', text[pos:]): continue
            for char in ('}',']'):
                repaired = text[:pos] + char + text[pos:]
                try:
                    value = json.loads(repaired)
                    jsonschema.Draft202012Validator(schema).validate(value)
                except (ValueError,jsonschema.ValidationError):
                    continue
                if repaired not in [r[0] for r in possibilities]:
                    possibilities.append((repaired,value,pos,char))
        if len(possibilities) != 1:
            raise ValueError('无法唯一地恢复单个闭合符；保留原失败响应')
        repaired,value,pos,char = possibilities[0]
        return value, dict(kind='local_syntax_recovery', original_request_succeeded=False,
            original_sha256=hashlib.sha256(text.encode()).hexdigest(),
            recovered_sha256=hashlib.sha256(repaired.encode()).hexdigest(),
            insertion=dict(character_offset=pos,text=char), status='directions_only_pending_implementation')
    raise ValueError('响应本身是合法 JSON，无需语法恢复')


def recover_saved_directions(ledger):
    """Explicit user resume only: require a complete assistant and error result."""
    from pathlib import Path
    folder = ledger.root/'directions'
    invocation = json.loads((folder/'invocation.json').read_text('utf8'))
    trace = Path(invocation.get('stream_trace_path',''))
    if not trace.is_file() or trace.stat().st_size > 8*1024*1024:
        raise ValueError('缺少有界完整终态日志，不能恢复部分响应')
    assistant, terminal = [], []
    with trace.open(encoding='utf8') as stream:
        for line in stream:
            entry = json.loads(line)
            try: packet = json.loads(entry.get('line',''))
            except (ValueError,TypeError): continue
            if packet.get('type') == 'assistant': assistant.append(packet.get('message',{}))
            if packet.get('type') == 'result': terminal.append(packet)
    if len(assistant)!=1 or len(terminal)!=1 or not terminal[0].get('is_error'):
        raise ValueError('终态或完整响应不唯一；不能从流片段恢复')
    text = ''.join(c.get('text','') for c in assistant[0].get('content',[]) if c.get('type')=='text')
    partial = (folder/'provider-partial.txt').read_text('utf8')
    if text != partial: raise ValueError('完整响应与保存稿不一致')
    from .authored_generation import direction_schema, legacy_direction_schema, normalize_directions
    recovered = []
    for schema in (direction_schema(), legacy_direction_schema()):
        try:
            recovered.append(recover_terminal_closure(text, schema))
        except ValueError:
            pass
    if len(recovered) != 1:
        raise ValueError('无法唯一匹配新旧方向协议；保留原失败响应')
    value, receipt = recovered[0]
    value = normalize_directions(value)
    receipt.update(provider=invocation.get('provider_id'), model=invocation.get('model'),
                   terminal=terminal[0], source_trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest())
    (folder/'local-direction-recovery.json').write_text(json.dumps(dict(directions=value,provenance=receipt),ensure_ascii=False,indent=2),'utf8')
    return value, receipt
