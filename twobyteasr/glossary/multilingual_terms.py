"""Concept names in the existing personal glossary file, with atomic edits.

Legacy rows retain their original bytes/fields and their ASR-only meaning.
Reading constructs an idempotent compatibility view; the first explicit edit
materializes it, with a pre-migration backup. No character-based language guess.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import re
import uuid
from functools import lru_cache
from pathlib import Path

LANGUAGES = {'und': '未指定', 'zh-Hans': '简体中文', 'zh-Hant': '繁體中文',
             'ja': '日本語', 'en': 'English', 'ko': '한국어', 'es-ES': 'Español',
             'de-DE': 'Deutsch', 'fr-FR': 'Français', 'pt-PT': 'Português (PT)',
             'pt-BR': 'Português (BR)', 'it-IT': 'Italiano', 'ru-RU': 'Русский'}


def locale(value):
    value = str(value or 'und').strip().replace('_', '-')
    return {'zh': 'zh-Hans', 'zh-CN': 'zh-Hans', 'zh-TW': 'zh-Hant',
            'zh-HK': 'zh-Hant', 'en-US': 'en', 'en-GB': 'en', 'ja-JP': 'ja', 'ko-KR': 'ko',
            'es': 'es-ES', 'de': 'de-DE', 'fr': 'fr-FR', 'pt': 'pt-PT', 'it': 'it-IT', 'ru': 'ru-RU'}.get(value, value)


def words(value):
    if isinstance(value, str):
        value = re.split(r'[\n|、；;]+', value)
    return list(dict.fromkeys(str(x).strip() for x in (value or ()) if str(x).strip()))


def name_record(name, *, confirmed=True, aliases=(), mishearings=(), mistranslations=(), **extra):
    name = str(name or '').strip()
    if not name or '\n' in name or '\r' in name:
        raise ValueError('请填写一行标准名称')
    return dict(extra, name=name, aliases=words(aliases), mishearings=words(mishearings),
                mistranslations=words(mistranslations), status='confirmed' if confirmed else extra.get('status', 'candidate'),
                confirmed=bool(confirmed))


def is_confirmed(row):
    return bool(row.get('confirmed')) and row.get('status') == 'confirmed'


def legacy_is_confirmed(row):
    """Use the same human authority gate as the pre-existing ASR snapshot."""
    from .terminology import mapping_is_confirmed
    provenance = str(row.get('provenance') or '').strip()
    manual = provenance == 'user_confirmed' or (not provenance and (
        row.get('verification') == 'user_manual' or 'user_manual' in row.get('sources', ())
        or row.get('origin') in {'手动', '批量导入', '用户确认'}
        or bool(row.get('confirmed')) and str(row.get('verification') or '').startswith('user_')))
    return manual and mapping_is_confirmed(row, inferred_manual=manual)


def concept(name, language='und', **kwargs):
    return dict(id='concept:' + uuid.uuid4().hex, names={locale(language): name_record(name)},
                candidates={}, category=kwargs.get('category', '其他'), description=kwargs.get('description', ''),
                categories=words([kwargs.get('category', '其他')]))


def concepts_from_entry(entry, library_id):
    result = copy.deepcopy(entry.get('concepts', []))
    owned = {tuple(key) for row in result for key in row.get('legacy_keys', ())}
    grouped = {}
    for row in entry.get('mappings', ()):
        if not isinstance(row, dict) or not row.get('from') or not row.get('to'):
            continue
        if (row['from'], row['to']) in owned:
            continue
        grouped.setdefault(str(row['to']), []).append(row)
    from .terminology import mapping_is_confirmed
    for target, rows in grouped.items():
        identity = 'concept:' + uuid.uuid5(uuid.NAMESPACE_URL, '2byte:' + str(library_id) + ':' + target).hex
        confirmed = any(legacy_is_confirmed(r) for r in rows)
        record = name_record(target, confirmed=confirmed,
            mishearings=[r['from'] for r in rows if r['from'] != target and legacy_is_confirmed(r)],
            sources=copy.deepcopy(rows), user_modified=confirmed, legacy=True,
            correction_enabled=any(r.get('correction_enabled', True) for r in rows),
            emphasis_enabled=any(r.get('emphasis_enabled', False) for r in rows),
            mishearing_enabled={r['from']: bool(r.get('correction_enabled', True)) for r in rows if r['from'] != target})
        result.append(dict(id=identity, names={'und': record}, candidates={},
            category=rows[0].get('category', '其他'), categories=words([r.get('category', '其他') for r in rows]),
            description='', legacy_keys=[[r['from'], r['to']] for r in rows], legacy_records=copy.deepcopy(rows)))
    return result


def library_entry(legacy, library_id, payload=None):
    payload = payload if payload is not None else (getattr(legacy, '_learned_term_payload_view', None) or legacy.load_learned_term_payload)()
    games = payload.get('games', {})
    key = legacy._glossary_entry_key(library_id, games)
    return key, games.get(key, {})


def read_concepts(legacy, library_id):
    key, entry = library_entry(legacy, library_id)
    return concepts_from_entry(entry, key or library_id)


def mutate(legacy, library_id, operation, *, expected=None):
    from .learning_review import storage_lock
    with storage_lock(legacy.LEARNED_TERMS_PATH):
        payload = legacy.load_learned_term_payload(strict=True)
        key, entry = library_entry(legacy, library_id, payload)
        if not key:
            key = legacy._glossary_write_key(library_id, payload.setdefault('games', {}))
            entry = payload['games'].setdefault(key, {'game': str(library_id), 'mappings': []})
        rows = concepts_from_entry(entry, key)
        if expected is not None:
            current = next((r for r in rows if r['id'] == expected['id']), None)
            comparable = lambda r: {k: v for k, v in (r or {}).items() if k != 'candidates'}
            if comparable(current) != comparable(expected):
                raise ValueError('词条已在别处修改，请重新打开后保存')
        result = operation(rows, entry)
        if any(not row.get('names') for row in rows):
            raise ValueError('最后一个名称需按删除词条处理')
        entry['concepts'] = rows
        entry['concept_schema'] = 1
        path = Path(legacy.LEARNED_TERMS_PATH)
        backup = path.with_name(path.name + '.pre-multilingual.bak')
        if path.exists() and not backup.exists():
            # A whole-file backup is made before the first new-schema write.
            from ..storage.atomic_files import write_text_atomic
            write_text_atomic(backup, path.read_text(encoding='utf-8-sig'))
        legacy._touch_glossary_entry(entry, key)
        legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
        return result


def save_concept(legacy, library_id, row, *, expected=None, input_language=None):
    value = copy.deepcopy(row)
    value.setdefault('id', 'concept:' + uuid.uuid4().hex)
    names = {}
    for code, record in value.get('names', {}).items():
        names[locale(code)] = name_record(**{**record, 'name': record.get('name', ''), 'confirmed': is_confirmed(record)})
    value['names'] = names
    def apply(rows, entry):
        index = next((i for i, r in enumerate(rows) if r['id'] == value['id']), None)
        if index is None:
            rows.append(value)
        else:
            # Background candidate arrivals do not block manual editing and
            # cannot be lost when an older editor draft is saved.
            value['candidates'] = copy.deepcopy(rows[index].get('candidates', {}))
            rows[index] = value
        if input_language:
            entry['last_input_language'] = locale(input_language)
        return copy.deepcopy(value)
    return mutate(legacy, library_id, apply, expected=expected)


def delete_concept(legacy, library_id, identity):
    def apply(rows, entry):
        deleted = next((r for r in rows if r['id'] == identity), None)
        if deleted is None:
            return False
        keys = {tuple(k) for k in deleted.get('legacy_keys', ())}
        entry['mappings'] = [r for r in entry.get('mappings', ()) if (r.get('from'), r.get('to')) not in keys]
        if deleted.get('reference_name'):
            entry['hidden_reference_terms'] = words([*entry.get('hidden_reference_terms', ()), deleted['reference_name']])
        rows.remove(deleted)
        return True
    return mutate(legacy, library_id, apply)


def merge_preview(first, second):
    return [dict(language=lang, current=first['names'][lang]['name'], incoming=name['name'])
            for lang, name in second['names'].items() if lang in first['names']
            and first['names'][lang]['name'] != name['name']]


def merge_concepts(first, second, decisions=None):
    value = copy.deepcopy(first)
    decisions = decisions or {}
    for conflict in merge_preview(first, second):
        if decisions.get(conflict['language']) not in {'current', 'incoming'}:
            raise ValueError('请选择同语言标准名称：' + conflict['language'])
    for lang, incoming in second['names'].items():
        old = value['names'].get(lang)
        if old is None:
            value['names'][lang] = copy.deepcopy(incoming)
            continue
        choose_incoming = decisions.get(lang) == 'incoming'
        chosen, other = (incoming, old) if choose_incoming else (old, incoming)
        new = copy.deepcopy(chosen)
        new['aliases'] = words([*chosen.get('aliases', ()), *other.get('aliases', ()),
                                *([other['name']] if old['name'] != incoming['name'] else [])])
        for key in ('mishearings', 'mistranslations', 'sources'):
            new[key] = copy.deepcopy(chosen.get(key, []))
            for item in other.get(key, ()):
                if item not in new[key]: new[key].append(copy.deepcopy(item))
        # Confirmation cannot be inherited across different standard names.
        if old['name'] == incoming['name'] and is_confirmed(other):
            new.update(status='confirmed', confirmed=True)
        new['user_modified'] = bool(old.get('user_modified') or incoming.get('user_modified'))
        value['names'][lang] = new
    value['categories'] = words([*value.get('categories', [value.get('category', '其他')]),
                                 *second.get('categories', [second.get('category', '其他')])])
    value['legacy_keys'] = [list(k) for k in dict.fromkeys(tuple(k) for r in (first, second) for k in r.get('legacy_keys', ()))]
    value['legacy_records'] = [*first.get('legacy_records', ()), *second.get('legacy_records', ())]
    value['linked_ids'] = words([*first.get('linked_ids', ()), second['id'], *second.get('linked_ids', ())])
    for lang, candidates in second.get('candidates', {}).items():
        dest = value.setdefault('candidates', {}).setdefault(lang, [])
        for candidate in candidates:
            if candidate not in dest: dest.append(copy.deepcopy(candidate))
    if second.get('description') and second.get('description') != value.get('description'):
        value['description'] = '\n'.join(filter(None, (value.get('description'), second['description'])))
    return value


def link_concepts(legacy, library_id, first_id, second_id, decisions=None, *, source_library=None):
    external = read_concepts(legacy, source_library) if source_library and source_library != library_id else None
    def apply(rows, entry):
        first = next(r for r in rows if r['id'] == first_id)
        second = next(r for r in (external if external is not None else rows) if r['id'] == second_id)
        if first_id == second_id and external is None: raise ValueError('不能关联自身')
        merged = merge_concepts(first, second, decisions)
        if external is not None:
            merged['legacy_keys'] = copy.deepcopy(first.get('legacy_keys', []))
            merged.setdefault('copied_from', []).append(dict(library_id=source_library, concept_id=second_id))
        rows[rows.index(first)] = merged
        if external is None: rows.remove(second)
        return copy.deepcopy(merged)
    return mutate(legacy, library_id, apply)


def default_language(legacy, library_id):
    _, entry = library_entry(legacy, library_id)
    return entry.get('last_input_language', entry.get('default_input_language', 'und'))


def set_default_language(legacy, library_id, language):
    def apply(rows, entry):
        entry['default_input_language'] = locale(language)
        entry['last_input_language'] = locale(language)
    mutate(legacy, library_id, apply)


def export_library(legacy, library_id):
    key, entry = library_entry(legacy, library_id)
    return dict(format='2byte-concepts-v1', library_id=key, name=entry.get('game', library_id),
                concepts=concepts_from_entry(entry, key), mappings=copy.deepcopy(entry.get('mappings', [])),
                default_input_language=entry.get('default_input_language', 'und'))


COLUMN_LANGUAGES = {'中文': 'zh-Hans', '简体中文': 'zh-Hans', '繁体中文': 'zh-Hant', '繁體中文': 'zh-Hant',
                    '日文': 'ja', '日语': 'ja', '英文': 'en', '英语': 'en', **{k: k for k in LANGUAGES}}


def parse_import(text, column_languages=None):
    raw = str(text).lstrip('\ufeff').strip()
    if raw.startswith(('{', '[')):
        value = json.loads(raw)
        rows = value if isinstance(value, list) else value.get('concepts')
        if rows is None:
            return concepts_from_entry(value, str(value.get('library_id', 'import')))
    else:
        dialect = '\t' if '\t' in raw.partition('\n')[0] else ','
        reader = csv.DictReader(io.StringIO(raw), delimiter=dialect)
        columns = dict(COLUMN_LANGUAGES if column_languages is None else column_languages)
        rows = []
        if not any(h in columns for h in reader.fieldnames or ()):
            raise ValueError('请在导入预览中指定名称列对应的语言')
        for record in reader:
            names = {locale(lang): name_record(record.get(h, ''), sources=['表格导入'])
                     for h, lang in columns.items() if lang and record.get(h, '').strip()}
            if names:
                rows.append(dict(id=record.get('id') or record.get('概念ID'), names=names,
                                 category=record.get('分类') or record.get('category') or '其他'))
    result = []
    for row in rows:
        row = copy.deepcopy(row)
        if not row.get('names'): raise ValueError('导入词条缺少名称')
        row['names'] = {locale(lang): name_record(**{**record, 'confirmed': is_confirmed(record)})
                        for lang, record in row['names'].items()}
        # Stable only for repeated identical imports. Never link by a shared name.
        if not row.get('id'):
            row['id'] = 'concept:' + uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(row, ensure_ascii=False, sort_keys=True)).hex
        result.append(row)
    return result


def import_preview(existing, incoming):
    index = {r['id']: r for r in existing}
    stats = dict(added=0, supplemented=0, conflicts=0, duplicates=0)
    conflicts = []
    for row in incoming:
        old = index.get(row['id'])
        if old is None:
            stats['added'] += 1
            index[row['id']] = row
        elif old == row:
            stats['duplicates'] += 1
        else:
            different = merge_preview(old, row)
            if different:
                stats['conflicts'] += len(different)
                conflicts.extend(dict(c, concept_id=row['id']) for c in different)
            else: stats['supplemented'] += 1
    return stats, conflicts


def import_concepts(legacy, library_id, incoming):
    def apply(rows, entry):
        stats, conflicts = import_preview(rows, incoming)
        for row in incoming:
            old = next((r for r in rows if r['id'] == row['id']), None)
            if old is None: rows.append(copy.deepcopy(row))
            else:
                if old == row: continue
                # Reimport/update never replaces a local preferred spelling.
                choices = {c['language']: 'current' for c in merge_preview(old, row)}
                merged = merge_concepts(old, row, choices)
                merged['linked_ids'] = old.get('linked_ids', [])
                for lang in choices:
                    merged['names'][lang] = copy.deepcopy(old['names'][lang])
                for lang, name in old['names'].items():
                    if name.get('user_modified') and is_confirmed(name):
                        merged['names'][lang] = copy.deepcopy(name)
                rows[rows.index(old)] = merged
        return stats, conflicts
    return mutate(legacy, library_id, apply)


SHORT_LANGUAGES = {'zh-Hans': '简', 'zh-Hant': '繁', 'ja': '日', 'en': 'EN', 'ko': '韩', 'und': '未定'}


def translation_state(value, code):
    """How a concept stands in one display language: confirmed, pending, candidate or missing."""
    row = value['names'].get(code)
    if row is not None:
        return 'confirmed' if is_confirmed(row) else 'pending'
    return 'candidate' if value.get('candidates', {}).get(code) else 'missing'


def card_rows(concepts, display_language=''):
    """One card per concept.  The card keeps its own (first) name; a display
    language adds a second line with that language's name and its state."""
    result = []
    for value in concepts:
        names = value['names']
        code = next(iter(names))
        row = names[code]
        confirmed = is_confirmed(row)
        codes = list(names)
        short = SHORT_LANGUAGES
        tag = short.get(code, code.upper()[:2]) + (f'+{len(codes)-1}' if len(codes) > 1 else '')
        note = ('尚无 ' + LANGUAGES.get(display_language, display_language)) if display_language and display_language not in names else ''
        translation = dict(translation_code='', translation='', translation_state='')
        if display_language and display_language != code:
            state = translation_state(value, display_language)
            text = names[display_language]['name'] if display_language in names else (
                value['candidates'][display_language][0].get('name', '') if state == 'candidate' else '')
            translation = dict(translation_code=short.get(display_language, display_language.upper()[:2]),
                               translation=text, translation_state=state)
        language_words = {'en': '英文 英语', 'ja': '日文 日语', 'zh-Hans': '中文 简体', 'zh-Hant': '中文 繁体 繁體', 'ko': '韩语 韓語'}
        search = ' '.join(str(x) for language, n in names.items()
                          for x in (language, LANGUAGES.get(language, ''), language_words.get(language, ''), n['name'], *n.get('aliases', ()), *n.get('mishearings', ())))
        result.append(dict(concept_id=value['id'], concept=value, term_text=row['name'], target=row['name'], source=row['name'],
            category=value.get('category', '其他'), categories=value.get('categories', [value.get('category', '其他')]), status='confirmed' if confirmed else 'candidate',
            raw={'concept_id': value['id'], 'from': row['name'], 'to': row['name']},
            origin_labels=['手动' if row.get('user_modified') else '词库'], heard=row.get('mishearings', []),
            languages=codes, language_tag=tag, language_note=note, **translation,
            pending_languages=[lang for lang, n in names.items() if not is_confirmed(n)] + list(value.get('candidates', {})),
            pending_name_count=sum(not is_confirmed(n) for n in names.values()) + sum(len(c) for c in value.get('candidates', {}).values()),
            tooltip=tag + ('\n' + note if note else ''), searchable=(search + ' ' + value.get('category', '')).casefold(),
            actions=('编辑', '删除')))
    return result


def hydrate_policy(value, legacy=None):
    """Resolve saved shared-library IDs once at task start, never per cue."""
    from .translation_terms import normalize
    value = normalize(value)
    if not value.get('concept_library_ids'):
        return value
    if legacy is None:
        import subtitle_core as legacy
    # Embedded concept libraries from a previous project snapshot are refreshed
    # only here. A FrozenTerms/TranslationSource is never hydrated again.
    value['libraries'] = [lib for lib in value['libraries'] if not lib.get('shared_concepts')]
    value['selected_ids'] = [i for i in value['selected_ids'] if not i.startswith('concept-library:')]
    for identity in value.get('concept_library_ids', ()):
        key, entry = library_entry(legacy, identity)
        if not key: continue
        lib_id = 'concept-library:' + key
        value['libraries'].append(dict(id=lib_id, name=entry.get('game', key), revision=entry.get('revision', 0),
            source_language='', target_language='', terms=[], concepts=concepts_from_entry(entry, key), shared_concepts=True))
        value['selected_ids'].append(lib_id)
    return value


def task_policy(value, legacy=None):
    """Capture once, including when RunOptions is replayed for another file."""
    from .translation_terms import normalize
    if isinstance(value, dict) and value.get('_frozen_concepts'):
        return normalize(value)
    result = hydrate_policy(value, legacy)
    result['_frozen_concepts'] = True
    return result


def direction_terms(library, source_language, target_language):
    source_code, target_code = locale(source_language), locale(target_language)
    rows = []
    for value in library.get('concepts', ()):
        source, target = (value.get('names', {}).get(code) for code in (source_code, target_code))
        if not source or not target or not is_confirmed(source) or not is_confirmed(target): continue
        rows.append(dict(source=source['name'], target=target['name'], confirmed=True, enabled=True,
            aliases=words(source.get('aliases', ())), target_aliases=words(target.get('aliases', ())),
            context=value.get('description', ''), concept_id=value['id'],
            mistranslations=words(target.get('mistranslations', ())),
            source_language=source_code, target_language=target_code))
    return rows


@lru_cache(maxsize=32)
def source_snapshot(snapshot, language):
    from dataclasses import replace
    from .terminology import GlossarySnapshot
    code = locale(language)
    return GlossarySnapshot(tuple(replace(lib, terms=tuple(t for t in lib.terms
        if t.language == code or ((not t.language or t.language == 'und')
                                  and code in {'zh-Hans', 'zh-Hant', 'und', 'auto'}))) for lib in snapshot.libraries))


def legacy_projection(entry):
    """Read compatibility only: never serialize target errors as ASR aliases."""
    owned = {tuple(k) for c in entry.get('concepts', ()) for k in c.get('legacy_keys', ())}
    rows = [copy.deepcopy(r) for r in entry.get('mappings', ()) if (r.get('from'), r.get('to')) not in owned]
    for c in entry.get('concepts', ()):
        for code, name in c['names'].items():
            for surface in (name['name'], *name.get('mishearings', ())):
                rows.append(dict(source_metadata=copy.deepcopy(name.get('sources', [])),
                    **{'from': surface, 'to': name['name']}, language=code, concept_id=c['id'],
                    category=c.get('category', '其他'), confirmed=is_confirmed(name),
                    correction_enabled=bool(name.get('correction_enabled', True) and name.get('mishearing_enabled', {}).get(surface, True)),
                    emphasis_enabled=bool(name.get('emphasis_enabled', False)),
                    provenance='user_confirmed' if is_confirmed(name) else 'candidate', origin='手动' if name.get('user_modified') else '用户确认'))
    return rows


def apply_source_terms(segments, legacy, *, snapshot=None):
    """Shared local/streaming ASR pass; the snapshot owns language and scope."""
    from .terminology import runtime_snapshot, apply_to_segments
    snapshot = runtime_snapshot(legacy) if snapshot is None else snapshot
    return apply_to_segments(segments, snapshot, legacy)


def _target_index(policy, language):
    """One indexed scan per cue; the frozen job owns its indices and lifetime."""
    from .translation_terms import freeze, match_text, _literal_pattern, language as base_language
    frozen = freeze(policy)
    key = locale(language)
    if not hasattr(frozen, '_target_error_indices'): frozen._target_error_indices = {}
    if key not in frozen._target_error_indices:
        value = frozen.value
        owners, rules, errors, formal = [], [], {}, {}
        for lib in value['libraries'] if value['enabled'] else ():
            if lib['id'] not in value['selected_ids']: continue
            for c in lib.get('concepts', ()):
                target = c.get('names', {}).get(key)
                if not target or not is_confirmed(target): continue
                owner = len(owners)
                owners.append(dict(concept=c, record=target, library_id=lib['id']))
                for name in (target['name'], *target.get('aliases', ())):
                    if match_text(name): formal.setdefault(match_text(name), set()).add(owner)
                for wrong in target.get('mistranslations', ()):
                    if not match_text(wrong): continue
                    errors.setdefault(match_text(wrong), []).append(len(rules))
                    rules.append(dict(source=wrong, target=target['name'], concept_id=c['id'],
                                      library_id=lib['id'], owner=owner))
        boundary = r'[A-Za-z0-9_]' if base_language(language) in {'zh', 'ja', 'ko'} else r'[\w]'
        frozen._target_error_indices[key] = (owners, rules, errors,
            _literal_pattern(errors, boundary) if errors else None, formal,
            _literal_pattern(formal, boundary) if formal else None)
    return frozen._target_error_indices[key]


def _target_matches(policy, language, text):
    from .translation_terms import match_text
    owners, rules, errors, pattern, formal, formal_pattern = _target_index(policy, language)
    normalized = match_text(text)
    formal_hits = list(formal_pattern.finditer(normalized)) if formal_pattern else []
    indices, protected = set(), set()
    for hit in pattern.finditer(normalized) if pattern else ():
        matched = errors.get(hit.group(), ())
        indices.update(matched)
        # A valid preferred name or legal alias, including a longer name,
        # wins over a contradictory error rule. Contextual AI review remains
        # possible; local rewriting cannot destroy another legitimate name.
        if any(name.start() <= hit.start() and hit.end() <= name.end() for name in formal_hits):
            protected.update(matched)
    owner_ids = {rules[i]['owner'] for i in indices}
    owner_ids.update(owner for hit in formal_hits for owner in formal.get(hit.group(), ()))
    return owners, rules, indices, protected, owner_ids


def target_candidates(policy, language, text):
    """Relevant target-only evidence, never an inferred source→target mapping."""
    owners, rules, indices, protected, owner_ids = _target_matches(policy, language, text)
    return [dict(concept_id=owners[i]['concept']['id'], library_id=owners[i]['library_id'],
        language=locale(language), name=owners[i]['record']['name'],
        aliases=list(owners[i]['record'].get('aliases', ())),
        wrong_in_text=list(dict.fromkeys(rules[j]['source'] for j in sorted(indices) if rules[j]['owner'] == i)),
        context=str(owners[i]['concept'].get('description') or '')[:240],
        ambiguous=any(rules[j]['owner'] == i for j in protected), purpose='existing_target_text_only')
        for i in sorted(owner_ids)]


def target_rules(policy, language, text, source_text='', source_language=''):
    """Only bounded, unambiguous errors with positive evidence execute locally."""
    from .translation_terms import matched_pairs, match_text
    owners, rules, indices, protected, _ = _target_matches(policy, language, text)
    candidates = []
    for i in sorted(indices - protected):
        row = rules[i]; owner = owners[row['owner']]
        c, target = owner['concept'], owner['record']
        source = c['names'].get(locale(source_language))
        associated = source and is_confirmed(source) and matched_pairs(
            [(s, s) for s in (source['name'], *source.get('aliases', ()))], source_text, source_language)
        anchor = matched_pairs([(s, s) for s in (target['name'], *target.get('aliases', ()))], text, language)
        context = str(c.get('description') or '').strip()
        contextual = context and matched_pairs([(context, context)], source_text + ' ' + text, language)
        if associated or anchor or contextual:
            candidates.append({key: value for key, value in row.items() if key != 'owner'})
    groups = {}
    for row in candidates: groups.setdefault(match_text(row['source']), set()).add(row['target'])
    return [row for row in candidates if len(groups[match_text(row['source'])]) == 1]
