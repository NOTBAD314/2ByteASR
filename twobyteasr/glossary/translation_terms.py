"""Direction-specific user terminology, independent of ASR alias correction.

Libraries live in optional project metadata. Frozen tasks carry their own copy;
old canonical/alias libraries are never inferred to be translation pairs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from ..diagnostics.text_work import measured, count

KEY = 'translation_terminology'
SOURCE_ENABLED = 'source_glossary_enabled'


class FrozenTerms:
    def __init__(self, policy):
        self.value = normalize(policy)
        self.serialized = json.dumps(self.value, ensure_ascii=False, sort_keys=True)
        self._indices = {}

    def index(self, source_language, target_language):
        key = (source_language, target_language)
        if key not in self._indices:
            self._indices[key] = _index(self.serialized, *key)
            count('term_rules_indexed', len(self._indices[key][0]))
        return self._indices[key]


def freeze(policy):
    return policy if isinstance(policy, FrozenTerms) else FrozenTerms(policy)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf8')).hexdigest()


def normalize(value):
    value = value if isinstance(value, dict) else {}
    libraries = []
    seen = set()
    raw_libraries = value.get('libraries', ())
    for library in raw_libraries if isinstance(raw_libraries, (list, tuple)) else ():
        if not isinstance(library, dict) or not isinstance(library.get('id'), (str, int)):
            continue
        identity = str(library['id'])
        if not identity or identity in seen: continue
        seen.add(identity)
        terms = []
        raw_terms = library.get('terms', ())
        for row in raw_terms if isinstance(raw_terms, (list, tuple)) else ():
            if not isinstance(row, dict):
                continue
            source, target = str(row.get('source') or '').strip(), str(row.get('target') or '').strip()
            if not source or not target:
                continue
            aliases = row.get('aliases', ())
            if isinstance(aliases, str):
                aliases = aliases.split('|')
            if not isinstance(aliases, (list, tuple)): aliases = ()
            terms.append(dict(source=source, target=target,
                aliases=list(dict.fromkeys(str(a).strip() for a in aliases if str(a).strip())),
                context=str(row.get('context') or '').strip()))
        libraries.append(dict(id=identity, name=str(library.get('name') or identity),
            source_language=str(library.get('source_language') or ''),
            target_language=str(library.get('target_language') or ''), terms=terms))
    selected = value.get('selected_ids', ())
    return dict(version=1, enabled=bool(value.get('enabled', False)),
                selected_ids=list(dict.fromkeys(str(i) for i in selected if str(i) in seen)) if isinstance(selected, (list, tuple)) else [], libraries=libraries)


def policy_of(project):
    return normalize((getattr(project, 'generation_metadata', None) or {}).get(KEY))


def language(code):
    return str(code or '').split('-')[0].lower()


@lru_cache(maxsize=24)
def _index(serialized, source_language, target_language):
    policy = json.loads(serialized)
    rows, surfaces = [], {}
    if policy['enabled']:
        for lib in policy['libraries']:
            if (lib['id'] not in policy['selected_ids'] or not lib['source_language'] or not lib['target_language']
                    or language(lib['source_language']) != language(source_language)
                    or lib['target_language'] != target_language):
                continue
            for term in lib['terms']:
                row = dict(term, library_id=lib['id'], library_name=lib['name'],
                           source_language=lib['source_language'], target_language=lib['target_language'])
                rows.append(row)
                for surface in (term['source'], *term['aliases']):
                    surfaces.setdefault(surface.casefold(), []).append(len(rows)-1)
    patterns = []
    boundary = r'[A-Za-z0-9_]' if language(source_language) in {'ja', 'zh', 'ko'} else r'[\w]'
    for surface in sorted(surfaces, key=lambda s: (-len(s), s)):
        escaped = re.escape(surface)
        if surface[0].isascii() and surface[0].isalnum():
            escaped = '(?<!' + boundary + ')' + escaped
        if surface[-1].isascii() and surface[-1].isalnum():
            escaped += '(?!' + boundary + ')'
        patterns.append(escaped)
    return rows, surfaces, re.compile('|'.join(patterns), re.IGNORECASE) if patterns else None


@measured('relevant')
def relevant(policy, source_language, target_language, text):
    """One indexed scan of a cue/context, no repeated whole-library payloads."""
    rows, surfaces, pattern = freeze(policy).index(source_language, target_language)
    if pattern is None:
        return []
    indices = {i for hit in pattern.finditer(str(text or '')) for i in surfaces.get(hit.group().casefold(), ())}
    return [copy.deepcopy(rows[i]) for i in sorted(indices)]


def matched_pairs(pairs, text, source_language=''):
    # Older inline mappings were explicitly entered as translation pairs.
    # They stay supported, but never acquire a direction from an ASR library.
    boundary = r'[A-Za-z0-9_]' if language(source_language) in {'ja', 'zh', 'ko'} else r'[\w]'
    return [(a, b) for a, b in pairs if re.search(
        ('(?<!' + boundary + ')' if a[:1].isascii() and a[:1].isalnum() else '') + re.escape(a) +
        ('(?!' + boundary + ')' if a[-1:].isascii() and a[-1:].isalnum() else ''), text, re.IGNORECASE)]


@measured('rule_version')
def rule_version(policy, pairs, source_language, target_language, text):
    rows, surfaces, pattern = freeze(policy).index(source_language, target_language)
    count('term_text_scans', bool(pattern))
    indices = ({i for hit in pattern.finditer(str(text or ''))
                for i in surfaces.get(hit.group().casefold(), ())} if pattern else ())
    rules = [{key: value for key, value in row.items() if key != 'library_name'}
             for row in (rows[i] for i in sorted(indices))]
    inline = matched_pairs(pairs, text, source_language)
    return digest([rules, inline]) if rules or inline else ''


def violations(source_text, translation, terms):
    """Report unambiguous required names; never perform a string replacement.

    Conditional/short/competing homonyms remain model/context decisions and
    require review, rather than mechanically treating ordinary words as names.
    """
    targets = {}
    for row in terms:
        targets.setdefault(row['source'].casefold(), set()).add(row['target'])
    return [dict(source=row['source'], target=row['target'], reason='术语译名未采用')
            for row in terms if not row.get('context') and len(row['source']) > 1
            and len(targets[row['source'].casefold()]) == 1
            and any(surface in source_text or surface.casefold() in source_text.casefold()
                    for surface in (row['source'], *row.get('aliases', ())))
            and not matched_pairs([(row['target'], row['target'])], translation, row.get('target_language', ''))]


def review_warnings(translation, terms):
    """Conditional/homonymous names need a visible review, not silent rewriting."""
    return [dict(source=row['source'], target=row['target'], context=row.get('context', ''),
                 reason='译名／语境需人工核对') for row in terms
            if not matched_pairs([(row['target'], row['target'])], translation, row.get('target_language', ''))]


PROMPT = '''用户配置的 translation_terminology 是本次语言方向的译名约定，优先于联网核验、通行译名、上下文旧译文和一般参考词。
每项 source/aliases 指源语词，target 是指定译名；context 为语境限制。结合整句和上下文判别同形异义，不把普通词机械当专名。
明确命中且语境符合时必须采用 target；有多个不同目标的同形词时按 context 选择，无法判定则保留并说明。绝不据此改写源文。'''
