"""One provider patch transaction for validator-owned MotionSpec numeric leaves.

Validation probes are private copies, never candidates or render input. Only a
strict patch returned by the current provider may change the delivered source.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
import uuid

from .theme_motion import MotionRangeError, validate_motion_spec

LEAF = re.compile(r'^motionSpec\.tracks\[(\d+)\]\.(from|to)\.([A-Za-z]+)$')


def request_motion_patch(client, issues, repair_id, schema, *, parent_request_id='', cancel_check=None):
    from .caption_creative_pipeline import canonical
    content='只修复 validator 列出的数值叶节点。保持原动作意图，在各闭区间内选取有限数字。仅输出严格 JSON {"patches":[{"candidate_index":0,"path":"精确白名单路径","value":数值}]}。根必须是对象，不得直接返回数组。禁止输出完整主题、名称、HTML、CSS或任何额外字段。\n'+canonical(dict(
        parent_request_id=parent_request_id,repair_request_id=repair_id,issues=issues))
    return client.complete([{'role':'user','content':content}],timeout=25,max_tokens=1800,
        json_schema=schema,cancel_check=cancel_check,operation_kind='numeric_patch',
        input_scope={'allowed_paths':[issue['path'] for issue in issues],'kind':'numeric_leaves_only'})


def changed_paths(before, after, path=''):
    """Type-sensitive structural diff; added/removed fields are changes too."""
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        return [p for key in sorted(before.keys() | after.keys())
                for p in ([f'{path}.{key}'.lstrip('.')] if key not in before or key not in after
                          else changed_paths(before[key], after[key], f'{path}.{key}'.lstrip('.')))]
    if isinstance(before, list):
        if len(before) != len(after): return [path]
        return [p for i, (a, b) in enumerate(zip(before, after)) for p in changed_paths(a, b, f'{path}[{i}]')]
    return [] if before == after else [path]


def collect_range_issues(payload):
    """Let the real validator enumerate numeric errors on validation-only copies.

    Only from/to leaves qualify. Scheduling, types and all structural failures
    remain fatal. Midpoint witnesses let the validator inspect subsequent
    fields; witnesses are never returned as a repair or persisted.
    """
    witness = copy.deepcopy(payload)
    issues = []
    for index, row in enumerate(witness['candidates']):
        spec = row['generated_source'].get('motionSpec')
        if not spec: continue
        for _ in range(32 * 2 * 14 + 1):
            try:
                validate_motion_spec(spec)
                break
            except MotionRangeError as exc:
                match = LEAF.fullmatch(exc.path)
                if not exc.repairable or not match: raise
                track, state, prop = match.groups()
                path = f'candidates[{index}].generated_source.{exc.path}'
                issues.append(dict(candidate_index=index, path=path, original_value=exc.value,
                                   original_type=type(exc.value).__name__, minimum=exc.low, maximum=exc.high))
                spec['tracks'][int(track)][state][prop] = (exc.low + exc.high) / 2
    return issues, witness


def patch_schema(issues):
    return {'type': 'object', 'additionalProperties': False, 'required': ['patches'], 'properties': {
        'patches': {'type': 'array', 'minItems': len(issues), 'maxItems': len(issues), 'items': {'anyOf': [
            {'type': 'object', 'additionalProperties': False, 'required': ['candidate_index', 'path', 'value'],
             'properties': {'candidate_index': {'type': 'integer', 'const': i['candidate_index']},
                            'path': {'type': 'string', 'const': i['path']},
                            'value': {'type': 'number', 'minimum': i['minimum'], 'maximum': i['maximum']}}}
            for i in issues]}}}}


def apply_patches(payload, result, issues):
    from .structured_output import response_object
    result = response_object(result)
    if set(result) != {'patches'} or not isinstance(result['patches'], list):
        raise ValueError('repair 只允许 patches 数组')
    allowed = {issue['path']: issue for issue in issues}
    if len(result['patches']) != len(allowed): raise ValueError('repair 必须覆盖所有且仅覆盖白名单字段')
    output = copy.deepcopy(payload)
    seen = set()
    for patch in result['patches']:
        if not isinstance(patch, dict) or set(patch) != {'candidate_index', 'path', 'value'}:
            raise ValueError('repair 含越权字段')
        path, value, index = patch['path'], patch['value'], patch['candidate_index']
        if not isinstance(path, str) or path not in allowed or path in seen:
            raise ValueError('repair 含未知或重复路径')
        issue = allowed[path]
        if type(index) is not int or index != issue['candidate_index']:
            raise ValueError('repair 候选索引不匹配')
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not issue['minimum'] <= value <= issue['maximum']):
            raise ValueError('repair 替换值必须是范围内有限数值')
        match = LEAF.fullmatch(path.split('.generated_source.', 1)[1])
        track, state, prop = match.groups()
        output['candidates'][index]['generated_source']['motionSpec']['tracks'][int(track)][state][prop] = value
        seen.add(path)
    diff = changed_paths(payload, output)
    if set(diff) != set(allowed): raise ValueError('repair 结构差异超出白名单')
    return output, diff


def repair_numeric_once(payload, *, validate, repair, ledger, provider, model, parent_request_id,
                        cancel_check=None):
    from .ai_providers import AIProviderError
    def check():
        if cancel_check and cancel_check():
            raise AIProviderError('当前 MotionSpec 修复已取消或请求已失效。', category='cancelled')
    check()
    try:
        validate(payload)
        return payload
    except ValueError:
        issues, witness = collect_range_issues(payload)
        if not issues: raise
    # Reject unrelated HTML/CSS/identity/DOM/material failures before any API.
    validate(witness)
    if repair is None:
        validate(payload)  # Preserve the original detailed error for offline callers.
    check()
    repair_id = uuid.uuid4().hex
    record = dict(parent_request_id=parent_request_id, repair_request_id=repair_id,
                  provider=provider, model=model, stage='motion_numeric_repair', issues=issues,
                  allowed_paths=[i['path'] for i in issues], changed_paths=[], status='requesting')
    ledger.value.setdefault('motion_repairs', []).append(record)
    ledger.save()
    started = time.monotonic()
    try:
        raw = repair(copy.deepcopy(issues), repair_id, patch_schema(issues))
        check()
        # Preserve this response separately; never replace provider-original.txt.
        from .provider_diagnostics import redact_diagnostics
        safe = redact_diagnostics(raw)
        (ledger.root / f'repair-{repair_id}.json').write_text(
            json.dumps(safe, ensure_ascii=False, allow_nan=False), encoding='utf8')
        repaired, diff = apply_patches(payload, raw, issues)
        check()
        validate(repaired)
        check()
        record.update(status='applied', changed_paths=diff,
                      patches=[dict(path=i['path'], before=i['original_value'],
                                    after=_leaf_value(repaired, i)) for i in issues])
        return repaired
    except Exception as exc:
        record.update(status='cancelled' if getattr(exc, 'category', '') == 'cancelled' else 'rejected',
                      error_type=type(exc).__name__)
        if getattr(exc, 'category', '') == 'cancelled': raise
        details = '; '.join(f"{i['path']} 原值={i['original_value']} 范围=[{i['minimum']}, {i['maximum']}]" for i in issues)
        raise ValueError(f'MotionSpec 一次定点修复失败：{details}；父请求 {parent_request_id}；修复请求 {repair_id}；{exc}') from exc
    finally:
        record['elapsed_seconds'] = round(time.monotonic() - started, 6)
        ledger.save()


def _leaf_value(payload, issue):
    track, state, prop = LEAF.fullmatch(issue['path'].split('.generated_source.', 1)[1]).groups()
    return payload['candidates'][issue['candidate_index']]['generated_source']['motionSpec']['tracks'][int(track)][state][prop]
