"""Direction-specific user terminology, independent of ASR alias correction.

Libraries live in optional project metadata. Frozen tasks carry their own copy;
old canonical/alias libraries are never inferred to be translation pairs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from ..diagnostics.text_work import measured, count

KEY = 'translation_terminology'
SOURCE_ENABLED = 'source_glossary_enabled'
MATCH_VERSION = 'concept-direction-v4-language-confirmation'


def match_text(text):
    value = unicodedata.normalize('NFKC', str(text or '')).casefold()
    value = re.sub(r'\s+', ' ', value).strip()
    # Layout spaces between CJK characters do not change a name. Latin word
    # boundaries remain intact, so Ann never matches Anna or an ordinary word.
    return re.sub(r'(?<=[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]) +(?=[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af])', '', value)


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
            from .terminology import mapping_is_confirmed
            terms.append(dict(source=source, target=target,
                confirmed=mapping_is_confirmed(row, inferred_manual=True),
                enabled=bool(row.get('enabled', row.get('correction_enabled', True))),
                aliases=list(dict.fromkeys(str(a).strip() for a in aliases if str(a).strip())),
                target_aliases=[str(a).strip() for a in row.get('target_aliases', ()) if str(a).strip()]
                    if isinstance(row.get('target_aliases'), (list, tuple)) else [],
                context=str(row.get('context') or '').strip()))
        libraries.append(dict(id=identity, name=str(library.get('name') or identity),
            source_language=str(library.get('source_language') or ''),
            target_language=str(library.get('target_language') or ''), terms=terms,
            concepts=copy.deepcopy(library.get('concepts', [])), shared_concepts=bool(library.get('shared_concepts')),
            revision=str(library.get('revision', ''))))
    selected = value.get('selected_ids', ())
    return dict(version=1, enabled=bool(value.get('enabled', False)),
                _frozen_concepts=bool(value.get('_frozen_concepts', False)),
                source_locale=str(value.get('source_locale', '')),
                concept_library_ids=list(dict.fromkeys(str(i) for i in value.get('concept_library_ids', ()))),
                preferred_libraries=copy.deepcopy(value.get('preferred_libraries', {})),
                selected_ids=list(dict.fromkeys(str(i) for i in selected if str(i) in seen)) if isinstance(selected, (list, tuple)) else [], libraries=libraries)


def policy_of(project):
    frozen = getattr(project, '_frozen_translation_policy', None)
    if frozen is not None: return normalize(frozen)
    from .multilingual_terms import hydrate_policy
    value = hydrate_policy((getattr(project, 'generation_metadata', None) or {}).get(KEY))
    if value.get('concept_library_ids'):
        from ..subtitle_rules.segmentation_profiles import project_language_tag
        code = project_language_tag(project)
        if language(code) == 'zh':
            from ..subtitle_rules.chinese_script import project_script
            code = project_script(project)
        value['source_locale'] = code
    return value


def language(code):
    return str(code or '').split('-')[0].lower()


def _literal_pattern(surfaces, boundary):
    """Factor shared literal prefixes while keeping longest, bounded matches.

    A flat alternation makes the regex parser repeat every shared prefix.
    Ten thousand numbered names blocked the first edit for over a second.
    The trie is temporary. Only the compiled pattern enters the bounded index
    cache. Very long terms and Unicode case-equivalent branches retain the
    original expression, including its exact ordering.
    """
    ordered = sorted(surfaces, key=lambda surface: (-len(surface), surface))
    if any(len(surface) > 128 or '\u0131' in surface for surface in ordered):
        patterns = []
        for surface in ordered:
            escaped = re.escape(surface)
            if surface[0].isascii() and surface[0].isalnum():
                escaped = '(?<!' + boundary + ')' + escaped
            if surface[-1].isascii() and surface[-1].isalnum():
                escaped += '(?!' + boundary + ')'
            patterns.append(escaped)
        return re.compile('|'.join(patterns), re.IGNORECASE)

    trie = {}
    for surface in ordered:
        node = trie
        for character in surface:
            node = node.setdefault(character, {})
        node[None] = '(?!' + boundary + ')' if surface[-1].isascii() and surface[-1].isalnum() else ''

    def expression(node):
        suffixes = {}
        for character, child in node.items():
            if character is not None:
                suffixes.setdefault(expression(child), []).append(character)
        branches = []
        for suffix, characters in suffixes.items():
            prefix = ''.join(re.escape(character) for character in characters)
            if len(characters) > 1:
                prefix = '[' + prefix + ']'
            branches.append(prefix + suffix)
        if None in node:
            branches.append(node[None])  # Longer matching terms precede this terminal.
        return branches[0] if len(branches) == 1 else '(?:' + '|'.join(branches) + ')'

    branches = []
    for character, node in trie.items():
        prefix = '(?<!' + boundary + ')' if character.isascii() and character.isalnum() else ''
        branches.append(prefix + re.escape(character) + expression(node))
    return re.compile('|'.join(branches), re.IGNORECASE)


@lru_cache(maxsize=24)
def _index(serialized, source_language, target_language):
    policy = json.loads(serialized)
    rows, surfaces = [], {}
    if policy['enabled']:
        for lib in policy['libraries']:
            if lib.get('shared_concepts'):
                if lib['id'] not in policy['selected_ids']: continue
                from .multilingual_terms import direction_terms
                source_locale = policy.get('source_locale', '')
                if language(source_locale) != language(source_language): source_locale = source_language
                terms = direction_terms(lib, source_locale, target_language)
            else:
                terms = lib['terms']
                if (not lib['source_language'] or not lib['target_language']
                        or language(lib['source_language']) != language(source_language)
                        or lib['target_language'] != target_language):
                    continue
            if lib['id'] not in policy['selected_ids']:
                continue
            for term in terms:
                if not term.get('confirmed', True) or not term.get('enabled', True):
                    continue
                row = dict(term, library_id=lib['id'], library_name=lib['name'],
                           source_language=source_language, target_language=target_language)
                rows.append(row)
                for surface in (term['source'], *term['aliases']):
                    surfaces.setdefault(match_text(surface), []).append(len(rows)-1)
    # Resolve explicit user priorities before matching, never file-read order.
    for surface, indices in list(surfaces.items()):
        preferred = policy.get('preferred_libraries', {}).get(surface)
        if preferred:
            chosen = [i for i in indices if rows[i]['library_id'] == preferred]
            if chosen: surfaces[surface] = chosen
        indices = surfaces[surface]
        if len({(rows[i].get('concept_id', rows[i]['target']), rows[i]['target']) for i in indices}) > 1:
            for i in indices: rows[i]['conflict'] = True
    boundary = r'[A-Za-z0-9_]' if language(source_language) in {'ja', 'zh', 'ko'} else r'[\w]'
    return rows, surfaces, _literal_pattern(surfaces, boundary) if surfaces else None


@measured('relevant')
def relevant(policy, source_language, target_language, text):
    """One indexed scan of a cue/context, no repeated whole-library payloads."""
    rows, surfaces, pattern = freeze(policy).index(source_language, target_language)
    if pattern is None:
        return []
    indices = {i for hit in pattern.finditer(match_text(text)) for i in surfaces.get(hit.group(), ())}
    return [copy.deepcopy(rows[i]) for i in sorted(indices)]


def matched_pairs(pairs, text, source_language=''):
    # Older inline mappings were explicitly entered as translation pairs.
    # They stay supported, but never acquire a direction from an ASR library.
    source_language = source_language or 'und'
    policy = effective_policy(freeze({}), tuple(pairs), source_language, '_inline')
    return [(row['source'], row['target']) for row in relevant(policy, source_language, '_inline', text)]


@lru_cache(maxsize=24)
def _effective_policy(serialized, pairs, source_language, target_language):
    policy = json.loads(serialized)
    rows, _, _ = freeze(policy).index(source_language, target_language)
    claimed = {match_text(surface) for row in rows for surface in (row['source'], *row['aliases'])}
    inline = [dict(source=a, target=b) for a, b in pairs if match_text(a) not in claimed]
    if inline:
        if not policy['enabled']:
            policy['selected_ids'] = []
        policy['enabled'] = True
        policy['libraries'].append(dict(id='__inline_translation__', name='补充译名对照',
            source_language=source_language, target_language=target_language, terms=inline))
        policy['selected_ids'].append('__inline_translation__')
    return freeze(policy)


def effective_policy(policy, pairs, source_language, target_language):
    """Freeze explicit directional libraries and user-entered translation pairs."""
    frozen = freeze(policy)
    pairs = tuple(pairs)
    if not pairs:
        return frozen
    return _effective_policy(frozen.serialized, pairs, source_language, target_language)


@measured('rule_version')
def rule_version(policy, pairs, source_language, target_language, text):
    rows = relevant(effective_policy(policy, pairs, source_language, target_language),
                    source_language, target_language, text)
    count('term_text_scans', 1)
    rules = [{key: value for key, value in row.items() if key != 'library_name'}
             for row in rows]
    return digest([MATCH_VERSION, rules]) if rules else ''


def violations(source_text, translation, terms):
    """Report unambiguous required names; never perform a string replacement.

    Conditional/short/competing homonyms remain model/context decisions and
    require review, rather than mechanically treating ordinary words as names.
    """
    targets = {}
    for row in terms:
        targets.setdefault(match_text(row['source']), set()).add(row['target'])
    return [dict(source=row['source'], target=row['target'], reason='术语译名未采用')
            for row in terms if not row.get('context') and len(row['source']) > 1
            and len(targets[match_text(row['source'])]) == 1
            and matched_pairs([(surface, surface) for surface in (row['source'], *row.get('aliases', ()))],
                              source_text, row.get('source_language', ''))
            and not matched_pairs([(target, target) for target in (row['target'], *row.get('target_aliases', ()))],
                                  translation, row.get('target_language', ''))]


def review_warnings(translation, terms):
    """Conditional/homonymous names need a visible review, not silent rewriting."""
    return [dict(source=row['source'], target=row['target'], context=row.get('context', ''),
                 reason='译名／语境需人工核对') for row in terms
            if not matched_pairs([(target, target) for target in (row['target'], *row.get('target_aliases', ()))],
                                 translation, row.get('target_language', ''))]


def validation_issues(source_text, translation, terms):
    """Conditional names require a valid choice or review, never a silent pass."""
    terms = [row for row in terms if not row.get('conflict')]
    issues = violations(source_text, translation, terms)
    groups = {}
    for row in terms:
        groups.setdefault(match_text(row['source']), []).append(row)
    for rows in groups.values():
        if len(rows[0]['source']) <= 1 or any(issue['source'] == rows[0]['source'] for issue in issues):
            continue
        if any(matched_pairs([(target, target) for target in (row['target'], *row.get('target_aliases', ()))],
                             translation, row.get('target_language', '')) for row in rows):
            continue
        # A free-text context is sometimes a restriction and sometimes a note.
        # Keep the existing text when the model cannot resolve it. A retry can
        # choose a contextual mapping, but absence of every name is not success.
        issues.extend(dict(source=row['source'], target=row['target'], context=row.get('context', ''),
                           reason='术语译名或适用语境尚未确认') for row in rows)
    return issues


PROMPT = '''用户配置的 translation_terminology 是本次语言方向的译名约定，优先于联网核验、通行译名、上下文旧译文和一般参考词。
conflict=true 表示用户尚未解决的同名冲突，不作为强制约束，不得按顺序随意选用。mistranslations 是错误译法，不是源语别名；target_aliases 是合法目标称呼。
每项 source/aliases 指源语词，target 是指定译名；context 为语境限制。结合整句和上下文判别同形异义，不把普通词机械当专名。
明确命中且语境符合时必须采用 target；有多个不同目标的同形词时按 context 选择，无法判定则保留并说明。绝不据此改写源文。'''
