"""One untrusted-input boundary for web theme identity and display metadata.

Only names and IDs may be recovered here. No visual field is invented or edited.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

NAME_MAX_LENGTH = 80
NAME_ALIASES = ('theme_name', 'display_name', 'title')
NAME_SCHEMA = {'type': 'string', 'minLength': 1, 'maxLength': NAME_MAX_LENGTH,
               'pattern': r'^(?!\s*$)[^\r\n\x00-\x1f]+$'}
ID_SCHEMA = {'type': 'string', 'minLength': 1, 'maxLength': 128,
             'pattern': r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$'}


def validate_name(value, path='webTheme.name'):
    if not isinstance(value, str):
        raise ValueError(f'{path}: 必须是字符串（收到 {type(value).__name__}）；请填写简短主题名后重试。')
    name = value.strip()
    if not name or len(name) > NAME_MAX_LENGTH or any(ord(c) < 32 for c in name):
        raise ValueError(f'{path}: 需要 1–{NAME_MAX_LENGTH} 字的单行名称；请填写简短主题名后重试。')
    return name


def validate_id(value, path='webTheme.id'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        raise ValueError(f'{path}: 需要合法的稳定标识；请重新导入完整主题。')
    return value


def normalize_theme_input(payload, *, path='webTheme'):
    """Unwrap the known legacy envelope and migrate names exactly once.

    A mixed envelope is ambiguous and rejected. Invalid explicit name types
    never become strings and cannot be hidden by a valid alias.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(f'{path}: 必须是主题对象；请重新生成结构化主题。')
    value = dict(payload)
    if 'WebTheme' in value:
        if len(value) != 1 or not isinstance(value['WebTheme'], Mapping):
            raise ValueError(f'{path}.WebTheme: 包装必须只包含一个主题对象；请展开后重试。')
        value = dict(value['WebTheme'])
    if 'name' in value and not isinstance(value['name'], str):
        validate_name(value['name'], path+'.name')
    missing = 'name' not in value or not value['name'].strip()
    if missing:
        for alias in NAME_ALIASES:
            try:
                name = validate_name(value.get(alias), path+'.'+alias)
            except ValueError:
                continue
            value['name'] = name
            break
    if 'name' in value and value['name'].strip():
        value['name'] = validate_name(value['name'], path+'.name')
    for alias in NAME_ALIASES:
        value.pop(alias, None)
    if 'id' in value:
        value['id'] = validate_id(value['id'], path+'.id')
    return value


def stable_theme_id(payload):
    visual = {k: v for k, v in payload.items() if k not in ('id', 'name', 'notes', 'concept', *NAME_ALIASES)}
    encoded = json.dumps(visual, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return 'theme-'+hashlib.sha256(encoded.encode('utf8')).hexdigest()[:24]


def parse_theme_input(raw):
    from .structured_output import response_object
    from .web_theme import parse_web_theme_sections
    try:
        parsed = response_object(raw)
    except ValueError:
        if not isinstance(raw, str) or not re.search(r'^\s*={2,}\s*(?:NAME|CUE_HTML|CUE_CSS)\s*={2,}', raw, re.I|re.M):
            raise
        parsed = parse_web_theme_sections(raw)
    return normalize_theme_input(parsed)


def recover_generated_names(themes, *, request_id, repair=None, cancel_check=None, event=None):
    """Validate visuals first, attempt ONE metadata-only batch, then name gaps.

    ``themes`` maps diagnostic paths to payloads. Repair gets only missing
    field paths and IDs, never HTML, CSS, fonts, captions or source media.
    """
    from .web_theme import WebThemeDocument
    from .ai_providers import AIProviderError
    from .structured_output import response_object

    def check():
        if cancel_check and cancel_check():
            raise AIProviderError('当前主题元数据修复已取消。', category='cancelled')

    check()
    normalized = {path: normalize_theme_input(value, path=path) for path, value in themes.items()}
    missing = []
    for path, value in normalized.items():
        try:
            if not value.get('name', '').strip():
                # This is a validation-only copy; the placeholder never escapes.
                probe = dict(value, name='metadata-validation')
                WebThemeDocument.from_dict(probe)
                missing.append(path)
            else:
                WebThemeDocument.from_dict(value)
        except ValueError as exc:
            raise ValueError(f'{path}: {exc}') from exc
    recovered = {}
    if missing and repair:
        check()
        if event: event('name_repair_started', {'paths': missing})
        try:
            result = response_object(repair([{'path': path, 'id': normalized[path].get('id', '')} for path in missing]))
            check()  # A cancelled/old request cannot apply its late repair.
            if set(result) != {'names'}:
                raise ValueError('metadataRepair: only names metadata is allowed')
            rows = result.get('names')
            if not isinstance(rows, list):
                raise ValueError('metadataRepair.names: expected array')
            for row in rows:
                if not isinstance(row, Mapping) or set(row) != {'path', 'name'}:
                    raise ValueError('metadataRepair.names: only path/name are allowed')
                path = row['path']
                if path not in missing or path in recovered:
                    raise ValueError('metadataRepair.names: duplicate or unknown path')
                recovered[path] = validate_name(row['name'], path+'.name')
        except Exception as exc:
            check()
            if getattr(exc, 'category', '') == 'cancelled': raise
            recovered = {}
            if event: event('name_repair_rejected', {'exception_type': type(exc).__name__})
    for path in missing:
        check()
        if path in recovered:
            normalized[path]['name'] = recovered[path]
            if event: event('name_repair_applied', {'path': path})
        else:
            # Include the complete request identity in the digest to avoid
            # collisions when requests share their first eight characters.
            suffix = hashlib.sha256((request_id+'|'+path).encode()).hexdigest()[:8]
            normalized[path]['name'] = f'AI主题-{request_id[:8]}-{suffix}'
            if event: event('name_fallback_applied', {'path': path, 'name': normalized[path]['name']})
    check()
    return normalized


def validate_theme_before_save(payload, *, path='webTheme'):
    """Persistence does not silently repair lost names or unwrap provider data."""
    from .web_theme import WebThemeDocument
    if not isinstance(payload, Mapping):
        raise ValueError(f'{path}: 保存需要完整主题对象。')
    validate_name(payload.get('name'), path+'.name')
    document = WebThemeDocument.from_dict(payload)
    document.validate()
    return document.to_dict()
