"""Typed JSON boundaries. Error summaries never contain model/user text."""
from collections.abc import Mapping
import json
import re


def object_value(value, path='$', *, pairs=False):
    if isinstance(value, str):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', value.strip())
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f'{path}: expected JSON object; received str (length={len(value)})') from None
    if isinstance(value, Mapping):
        return dict(value)
    if pairs and isinstance(value, (list, tuple)):
        result = {}
        for index, item in enumerate(value):
            if not isinstance(item, (list, tuple)) or len(item) != 2 or not isinstance(item[0], str):
                raise ValueError(f'{path}[{index}]: expected [string key, value]; received {type(item).__name__}')
            if item[0] in result:
                raise ValueError(f'{path}[{index}]: duplicate key')
            result[item[0]] = item[1]
        return result
    size = f' (length={len(value)})' if isinstance(value, (list, tuple, str)) else ''
    raise ValueError(f'{path}: expected object; received {type(value).__name__}{size}')


class StructuredResponseError(ValueError):
    def __init__(self, message, category):
        super().__init__(message)
        self.category = category


def response_object(raw, path='$', *, protocol=None):
    """Accept one object or typed JSONL with exactly one terminal result.

    Progress/warnings cannot become content, and arbitrary lists are not maps.
    """
    if not isinstance(raw, str):
        return object_value(raw, path)
    text = raw.strip()
    fenced = text.startswith('```')
    if fenced:
        match = re.fullmatch(r'```(?:json)?\s*\n?([\s\S]*?)\s*```', text)
        if not match:
            raise StructuredResponseError(f'{path}: incomplete fenced JSON (chars={len(raw)})', 'structured_output_truncated')
        text = match[1]
    lines = [(index, line) for index, line in enumerate(text.splitlines()) if line.strip()]
    # JSONL is a protocol, never a fallback for a broken pretty-printed object.
    first = None
    if lines and not fenced:
        try:
            first = json.loads(lines[0][1])
        except json.JSONDecodeError:
            pass
    typed = isinstance(first, dict) and ('type' in first or 'event' in first)
    if protocol == 'jsonl' or (protocol is None and typed and len(lines) > 1):
        finals = []
        for ordinal, (index, line) in enumerate(lines):
            packet = object_value(line, f'{path}.jsonl[{index}]')
            kind = packet.get('type', packet.get('event'))
            if kind in {'error', 'cancelled', 'canceled', 'response.failed', 'turn.failed', 'response.incomplete'}:
                category = 'cancelled' if kind in {'cancelled', 'canceled'} else 'provider_terminal_error'
                raise StructuredResponseError(f'{path}.jsonl[{index}]: terminal {kind}', category)
            if kind in {'progress', 'warning', 'thread.started', 'turn.started', 'turn.completed'}:
                continue
            if kind in {'result', 'final', 'response.completed'}:
                finals.append(packet.get('result', packet.get('response', packet.get('data'))))
            elif kind == 'item.completed' and isinstance(packet.get('item'), Mapping):
                if packet['item'].get('type') == 'agent_message':
                    finals.append(packet['item'].get('text'))
            elif kind is None and ordinal == len(lines)-1:
                # Some text transports emit progress JSONL followed by the
                # unwrapped final theme object. Only the last line qualifies.
                finals.append(packet)
            else:
                raise ValueError(f'{path}.jsonl[{index}]: unsupported message type') from None
        if len(finals) != 1:
            raise StructuredResponseError(f'{path}: expected one final JSONL result; received {len(finals)}', 'conflicting_final' if finals else 'provider_no_body') from None
        return object_value(finals[0], path+'.result')
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        incomplete = exc.msg.startswith('Unterminated') or exc.pos >= len(text.rstrip()) - 1
        category = 'structured_output_truncated' if incomplete else 'structured_output_invalid_json'
        label = 'incomplete JSON' if incomplete else 'invalid JSON'
        raise StructuredResponseError(f'{path}: {label}; chars={len(raw)}, line={exc.lineno}, column={exc.colno}', category) from None
    # A JSON string is a string, even if its contents resemble another object.
    if isinstance(value, str):
        raise ValueError(f'{path}: expected object; received str (length={len(value)})')
    return object_value(value, path)
