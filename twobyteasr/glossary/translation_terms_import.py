"""Strict all-or-nothing parsing and explicit, non-destructive terminology merge."""
from __future__ import annotations
import copy
import csv
import io
import json
import uuid

from .translation_terms import normalize


def term_key(term):
    return (term['source'], term['target'], tuple(sorted(term['aliases'])), term['context'])


def unique_terms(terms):
    result, seen, duplicates = [], set(), 0
    for term in terms:
        key = term_key(term)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key); result.append(copy.deepcopy(term))
    return result, duplicates


def parse_libraries(text, *, is_json, name, source_language, target_language):
    from ..subtitle_rules.subtitle_translation import SOURCE_LANGUAGES, TARGETS
    if is_json:
        value = json.loads(text)
        libs = value.get('libraries') if isinstance(value, dict) else None
        if not isinstance(libs, list) or not libs:
            raise ValueError('请选择含 libraries 和明确语言方向的翻译词库 JSON；原文校对库不能自动转换。')
    else:
        terms = []
        for number, row in enumerate(csv.reader(io.StringIO(text), delimiter='\t'), 1):
            if not row or not any(c.strip() for c in row):
                continue
            if len(row) != 2 or not all(c.strip() for c in row):
                raise ValueError(f'第 {number} 行必须是两列 TSV：源语言术语、标准译名。')
            if not terms and tuple(c.strip().casefold() for c in row) in (
                    ('source', 'target'), ('源语言术语', '标准译名')):
                continue
            terms.append(dict(source=row[0].strip(), target=row[1].strip(), aliases=[], context=''))
        if not terms:
            raise ValueError('没有读取到源语言术语和标准译名')
        libs = [dict(name=name, source_language=source_language, target_language=target_language, terms=terms)]
    result = []
    for index, raw in enumerate(libs, 1):
        if not isinstance(raw, dict):
            raise ValueError(f'第 {index} 个词库不是有效对象')
        if raw.get('source_language') not in SOURCE_LANGUAGES or raw.get('target_language') not in TARGETS:
            raise ValueError(f'第 {index} 个词库的语言方向无效，请使用窗口列出的语言代码。')
        terms = raw.get('terms')
        if not isinstance(terms, list):
            raise ValueError(f'第 {index} 个词库缺少 terms 列表')
        for number, term in enumerate(terms, 1):
            if not isinstance(term, dict) or any(not isinstance(term.get(k), str) or not term[k].strip()
                    for k in ('source', 'target')):
                raise ValueError(f'第 {index} 个词库第 {number} 条术语必须同时填写 source / target')
            aliases = term.get('aliases', [])
            if not isinstance(aliases, (str, list)) or isinstance(aliases, list) and any(not isinstance(a, str) for a in aliases):
                raise ValueError(f'第 {index} 个词库第 {number} 条 aliases 无效')
            if not isinstance(term.get('context', ''), str):
                raise ValueError(f'第 {index} 个词库第 {number} 条 context 无效')
        lib = dict(raw, id=uuid.uuid4().hex, name=str(raw.get('name') or name))
        result.append(normalize(dict(libraries=[lib]))['libraries'][0])
    return result


def merge_library(existing, imported, decisions=None):
    """Same source may have several meanings; never overwrite without a choice.

    Decisions are per source group: keep (default), imported, or both. Choosing
    imported explicitly replaces the displayed existing group, including contexts.
    """
    if (existing['source_language'], existing['target_language']) != (imported['source_language'], imported['target_language']):
        raise ValueError('语言方向不一致，不能追加到当前词库；请改选“导入为新词库”。')
    incoming, duplicates = unique_terms(imported['terms'])
    terms = copy.deepcopy(existing['terms'])
    by_source, candidates, conflicts = {}, {}, []
    for term in terms:
        by_source.setdefault(term['source'].casefold(), []).append(term)
    known = {term_key(t) for t in terms}
    for term in incoming:
        if term_key(term) in known:
            duplicates += 1
        else:
            candidates.setdefault(term['source'].casefold(), []).append(term)
    added = replaced = 0
    for source, rows in candidates.items():
        old = by_source.get(source, [])
        if not old:
            terms.extend(copy.deepcopy(rows)); added += len(rows)
            continue
        conflicts.append(dict(source=rows[0]['source'], key=source, existing=copy.deepcopy(old), incoming=copy.deepcopy(rows)))
        choice = (decisions or {}).get(source, 'keep')
        if choice == 'both':
            terms.extend(copy.deepcopy(rows)); added += len(rows)
        elif choice == 'imported':
            replacement = [t for t in incoming if t['source'].casefold() == source]
            terms = [t for t in terms if t['source'].casefold() != source] + copy.deepcopy(replacement)
            replaced += len(replacement)
    result = copy.deepcopy(existing); result['terms'] = terms
    return result, dict(added=added, duplicates=duplicates, conflicts=sum(len(c['incoming']) for c in conflicts),
                        replaced=replaced), conflicts
