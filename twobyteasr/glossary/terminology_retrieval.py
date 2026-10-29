"""Readonly, task-snapshot Chinese term recall; similarity never edits text."""
from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
import copy
import hashlib
import re

from ..subtitle_rules.text_similarity import levenshtein, phonetic_text

RULE_VERSION = 'glossary-context-recall-v10-enabled-library-gaps'
_CONTENT = re.compile(r'[^\w\u4e00-\u9fff]', re.UNICODE)
_LATIN_TOKEN = re.compile(r'(?<![A-Za-z0-9_])[A-Za-z0-9_]+(?![A-Za-z0-9_])')
_LATIN_IDENTIFIER = re.compile(r'[A-Za-z0-9_]{3,16}')
ASR_FIELDS = ('text', 'moss_text', 'firered_text', 'qwen_asr_text', 'firered_llm_text', 'alternate_text')
_COMMON_SINGLE_HANZI = frozenset('这那的了着地得他她它你我也和是不在有把')


def content(value):
    return _CONTENT.sub('', str(value or '')).casefold()


def latin_identifier_similarity(left, right):
    """Bounded whole-token recall for names; this never normalizes user text.

    Digit/letter shape and repeated letters are common ASR ID evidence. Short
    English words (So, of, op) cannot acquire fuzzy name authority here.
    """
    left, right = str(left).casefold(), str(right).casefold()
    if not all(_LATIN_IDENTIFIER.fullmatch(x) and sum(c.isalpha() for c in x) >= 2
               for x in (left, right)):
        return 0.
    if left == right:
        return 1.
    shape = lambda x: x.replace('0', 'o')
    a, b = shape(left), shape(right)
    collapsed = lambda x: re.sub(r'([a-z])\1+', r'\1', x)
    if collapsed(a) == collapsed(b):
        return .94
    distance = levenshtein(a, b)
    if distance > max(1, min(len(a), len(b)) // 4) or abs(len(a)-len(b)) > 1:
        return 0.
    similarity = SequenceMatcher(None, a, b, autojunk=False).ratio()
    return similarity if similarity >= .80 else 0.


def entity_category(category):
    label = str(category).lower()
    for name, words in (('player', ('选手', 'player', '人名', '昵称')),
            ('team', ('战队', 'team')), ('character', ('角色', '特工', 'character', 'agent')),
            ('skill', ('技能', 'skill', 'ability')), ('item', ('武器', '物品', 'weapon', 'item')),
            ('location', ('地图', '点位', '地点', 'map', 'location')),
            ('action', ('动作', 'action'))):
        if any(word in label for word in words):
            return name
    return 'unknown'


@lru_cache(maxsize=16)
def _catalog_index(snapshot):
    """Immutable snapshot/revision keys cache catalog and pronunciation once."""
    from .terminology import TermResolver
    spellings = TermResolver(snapshot).canonical_spellings
    catalog = {}
    for library in snapshot.libraries:
        from ..recognition.content_scene import library_domain
        domain_id, domain_name = library_domain(library)
        for term in library.terms:
            if not term.canonical or not term.correction_enabled:
                continue
            canonical = spellings.get(term.canonical.casefold(), term.canonical)
            row = catalog.setdefault(canonical, {'canonical': canonical,
                'aliases': [], 'status': 'reference', 'sources': [], 'matches': [], 'score': 0.})
            if term.confirmed:
                row['status'] = 'confirmed'
            row['aliases'] = list(dict.fromkeys([*row['aliases'], *term.aliases]))
            source = {'library_id': library.id, 'library_name': library.name,
                'provenance': term.provenance, 'origin': term.origin, 'category': term.category,
                'status': 'confirmed' if term.confirmed else 'reference',
                'domain_id': domain_id, 'domain_name': domain_name}
            if source not in row['sources']:
                row['sources'].append(source)
        for name in library.reference_terms:
            if not name:
                continue
            canonical = spellings.get(name.casefold(), name)
            row = catalog.setdefault(canonical, {'canonical': canonical, 'aliases': [], 'status': 'reference',
                'sources': [], 'matches': [], 'score': 0.})
            source = {'library_id': library.id, 'library_name': library.name,
                'provenance': 'reference_catalog', 'origin': '参考资料', 'category': 'reference',
                'status': 'reference'}
            if source not in row['sources']:
                row['sources'].append(source)
    for row in catalog.values():
        row['candidate_id'] = 'term-' + hashlib.sha256((row['canonical'] + '\0' +
            '\0'.join(sorted(s['library_id'] for s in row['sources']))).encode('utf-8')).hexdigest()[:12]
        row['entity_types'] = list(dict.fromkeys(entity_category(source['category']) for source in row['sources']))
    sounds = {content(variant): phonetic_text(content(variant)) for row in catalog.values()
        for variant in (row['canonical'], *row['aliases'])}
    return catalog, sounds


def _quick_ratio(left, right):
    """Upper bound of SequenceMatcher.ratio(): shared characters as a multiset."""
    if not left or not right:
        return 1.0 if left == right else 0.0
    available = {}
    for char in right:
        available[char] = available.get(char, 0) + 1
    shared = 0
    for char in left:
        count = available.get(char, 0)
        if count:
            available[char] = count - 1
            shared += 1
    return 2.0 * shared / (len(left) + len(right))


def retrieve_candidates(snapshot, segments, context_before='', context_after='', *, scene=None):
    """Complete enabled recall with per-position evidence; fuzzy rows never edit."""
    catalog, variant_sounds = _catalog_index(snapshot)
    catalog = copy.deepcopy(catalog)
    texts = []
    primary_texts = []
    latin_tokens = defaultdict(list)
    def add_text(cue_id, field, raw):
        raw = str(raw or '')
        indices = [index for index, char in enumerate(raw) if not _CONTENT.fullmatch(char)
            for _ in char.casefold()]
        value = content(raw)
        if value:
            texts.append((cue_id, field, value, indices))
        for match in _LATIN_TOKEN.finditer(raw):
            latin_tokens[match.group().casefold()].append((cue_id, field, match.start(), match.end()))
    for segment in segments:
        primary_texts.append((segment.segment_id, str(segment.text or '')))
        for field in ASR_FIELDS:
            add_text(segment.segment_id, field, getattr(segment, field, ''))
    for field, value in (('context_before', context_before), ('context_after', context_after)):
        add_text(None, field, value)
    # Whole Chinese word tokens only: a syllable inside an ordinary compound
    # is not a player mention. Tokenize once per primary cue, not per term.
    lengths = {len(content(variant)) for row in catalog.values()
        for variant in (row['canonical'], *row['aliases']) if 2 <= len(content(variant)) <= 12}
    lengths = {size for n in lengths for size in (n-1, n, n+1) if 2 <= size <= 12}
    windows = defaultdict(list)
    by_char, by_sound = defaultdict(set), defaultdict(set)
    sounds = {}
    for cue_id, field, text, indices in texts:
        for n in lengths:
            for start in range(max(0, len(text)-n+1)):
                value = text[start:start+n]
                windows[value].append((cue_id, field, indices[start], indices[start+n-1]+1))
    for value in windows:
        sound = sounds[value] = phonetic_text(value)
        for char in set(value):
            by_char[(len(value), char)].add(value)
        by_sound[(len(value), sound[:2])].add(value)
        by_sound[(len(value), sound[-2:])].add(value)
    retrieved = []
    for row in catalog.values():
        best = {}
        for variant in (row['canonical'], *row['aliases']):
            term = content(variant)
            if re.fullmatch(r'[A-Za-z0-9_]+', str(variant)):
                # Latin aliases must also be full tokens: "op" inside a
                # player's "Sop" is not evidence for the weapon alias.
                for heard, occurrences in latin_tokens.items():
                    score = 1. if heard == term else latin_identifier_similarity(term, heard)
                    if not score:
                        continue
                    for cue_id, field, start, end in occurrences:
                        key = (cue_id, field, start, end)
                        match = {'cue_id': cue_id, 'asr_source': field, 'heard': heard,
                            'start': start, 'end': end,
                            'score': round(score, 4), 'method': 'exact' if score == 1. else 'latin_identifier',
                            'matched_variant': variant, 'matched_alias': variant != row['canonical']}
                        if key not in best or score > best[key]['score']:
                            best[key] = match
                continue
            if not 2 <= len(term) <= 12:
                continue
            sound = variant_sounds[term]
            pool = set()
            for n in (len(term)-1, len(term), len(term)+1):
                for char in set(term):
                    pool.update(by_char.get((n, char), ()))
                pool.update(by_sound.get((n, sound[:2]), ()))
                pool.update(by_sound.get((n, sound[-2:]), ()))
            threshold = .94 if len(term) == 2 else .86
            for heard in pool:
                exact = heard == term
                if not exact:
                    # difflib's ratio never exceeds its multiset quick ratio,
                    # so a pair whose bound misses the gate cannot match
                    # (2026-10-10: 880k ratio calls per 193-caption review).
                    penalty = abs(len(term)-len(heard))*.10
                    spelling_bound = _quick_ratio(term, heard)
                    phonetic_bound = _quick_ratio(sound, sounds[heard])
                    if (max(spelling_bound, phonetic_bound) - penalty < threshold
                            or (spelling_bound < .5 and phonetic_bound < .90)):
                        continue
                spelling = SequenceMatcher(None, term, heard, autojunk=False).ratio()
                phonetic = SequenceMatcher(None, sound, sounds[heard], autojunk=False).ratio()
                score = max(spelling, phonetic) - abs(len(term)-len(heard))*.10
                if not exact and (score < (.94 if len(term)==2 else .86)
                                  or (spelling < .5 and phonetic < .90)):
                    continue
                method = 'exact' if exact else 'phonetic' if phonetic >= spelling else 'spelling'
                for cue_id, field, start, end in windows[heard]:
                    key = (cue_id, field, start, end)
                    match = {'cue_id': cue_id, 'asr_source': field, 'heard': heard,
                             'start': start, 'end': end,
                             'score': round(score, 4), 'method': method,
                             'matched_variant': variant, 'matched_alias': variant != row['canonical']}
                    if key not in best or score > best[key]['score']:
                        best[key] = match
        if not best:
            continue
        row['matches'] = list(best.values())
        row['score'] = max(x['score'] for x in row['matches'])
        row['weak_only'] = all(x['method'] == 'single_hanzi_weak' for x in row['matches'])
        row['ambiguous'] = False
        row['domain_source'] = getattr(scene, 'source', 'unknown')
        retrieved.append(row)
    # A small roster from the enabled library is useful match context even if
    # a commentator used an alias the library does not contain. Context-only
    # entries cannot authorize an automatic replacement.
    player = lambda row: any('选手' in str(s.get('category', ''))
        or 'player' in str(s.get('category', '')).lower() for s in row['sources'])
    active_libraries = {library.id for library in snapshot.libraries}
    if any(re.search(r'[\u4e00-\u9fff]', str(segment.text)) for segment in segments):
        present = {row['canonical'] for row in retrieved}
        peers = [row for row in catalog.values() if row['canonical'] not in present
            and row['status'] == 'confirmed' and player(row)
            and any(s['library_id'] in active_libraries for s in row['sources'])]
        # Large general catalogs are not match rosters; do not take a first-N.
        if len(peers) <= 48:
            for row in peers:
                row.update(matches=[{'cue_id': None, 'asr_source': 'context',
                    'heard': '', 'score': .50, 'method': 'enabled_roster_context',
                    'authority': 'review_only'}], score=.50, weak_only=True, ambiguous=False)
                retrieved.append(row)
    # Legal Chinese nouns after an ability/item verb can still be misheard.
    # Entity role only recalls options; no spelling/phonetic authority is added.
    present = {row['canonical'] for row in retrieved}
    for segment in segments:
        for mention in re.finditer(r'交出(?:了)?(?P<object>[\u4e00-\u9fff]{2,4})', str(segment.text)):
            options = [row for row in catalog.values()
                if any(kind in row['entity_types'] for kind in ('skill', 'item'))]
            if len(options) > 24:
                continue
            for row in options:
                if row['canonical'] not in present:
                    row.update(matches=[], score=.35, weak_only=True, ambiguous=False)
                    retrieved.append(row); present.add(row['canonical'])
                else:
                    row = next(value for value in retrieved if value['canonical'] == row['canonical'])
                row['matches'].append({'cue_id': segment.segment_id, 'asr_source': 'text',
                    'heard': mention['object'], 'start': mention.start('object'), 'end': mention.end('object'),
                    'score': .35, 'method': 'entity_role_context', 'entity_role': 'skill_or_item',
                    'authority': 'review_only', 'acoustic_verified': False})
    from .terminology_support import enrich_reference_bridges
    enrich_reference_bridges(retrieved, segments)
    competitors = defaultdict(list)
    for row in retrieved:
        for match in row['matches']:
            if (match['cue_id'] is not None and match['asr_source'] == 'text'
                    and (match['score'] >= .80 or match['method'] == 'single_hanzi_weak')):
                competitors[(match['cue_id'], match['heard'])].append((row, match['score']))
    for rows in competitors.values():
        high = max(score for _, score in rows)
        competing = [row for row, score in rows if high-score <= .04]
        if len({row['canonical'] for row in competing}) > 1:
            for row in competing:
                row['ambiguous'] = True
    return sorted(retrieved, key=lambda row: (-(row['score'] >= .97),
        -(row['status']=='confirmed'), -row['score'], row['canonical']))


def position_balanced_candidates(candidates):
    """One candidate per suspicious position before unrelated second choices.

    Exact matches retain authority and priority. Budget rejection may remove
    lower ranked alternatives, but a global high-frequency name cannot use up
    the entire allowance ahead of another cue's first candidate.
    """
    queues = defaultdict(list)
    for row in candidates:
        keys = {(match.get('cue_id'), match.get('start'), match.get('end'))
            for match in row.get('matches', ()) if match.get('cue_id') is not None}
        for key in keys or {(None, None, None)}:
            queues[key].append(row)
    output, seen = [], set()
    ordered = sorted(queues, key=lambda key: tuple(-1 if value is None else value for value in key))
    while any(queues.values()):
        for key in ordered:
            if queues[key]:
                row = queues[key].pop(0)
                if row['canonical'] not in seen:
                    seen.add(row['canonical']); output.append(row)
    exact = [row for row in output if row['score'] >= .97]
    return exact + [row for row in output if row['score'] < .97]


def latin_identifier_patch_supported(source, target, basis, candidates, cue_id=None, cue_text=''):
    """Validate a model's contextual ID patch, without treating recall as an edit.

    Only a sent, confirmed, unambiguous canonical is eligible. Its complete
    primary token must be a bounded typo and the model must explicitly cite
    glossary+context. Chinese transliterations and two-letter words retain
    the independent ASR/ambiguity rules below.
    """
    row = next((x for x in candidates if x.get('canonical') == target), None)
    if (row is None or row.get('status') != 'confirmed' or row.get('ambiguous')
            or not ('glossary' in basis.lower() or '词库' in basis)
            or not ('context' in basis.lower() or '语境' in basis)
            or not latin_identifier_similarity(source, target)):
        return False
    # A different explicitly enabled name is never a typo of this name.
    if any(x.get('canonical', '').casefold() == source.casefold()
           and x.get('canonical') != target for x in candidates):
        return False
    if not any(m.group() == source for m in _LATIN_TOKEN.finditer(cue_text)):
        return False
    return any(x.get('cue_id') == cue_id and x.get('asr_source') == 'text'
        and x.get('heard') == source.casefold() and x.get('score', 0) >= .80
        for x in row.get('matches', ()))


def short_latin_identifier_patch_supported(source, target, basis, candidates, cue_id=None,
                                          cue_text='', moss_text=''):
    """Validate a model proposal against this cue's MOSS ID and repeated IDs.

    Two-letter English alone remains insufficient. MOSS is not an extra
    independent vote when it owns the primary transcript. A deleted particle
    needs exact whole-sentence MOSS support after canonical spelling only.
    """
    row = next((x for x in candidates if x.get('canonical') == target), None)
    short = re.fullmatch(r'([A-Za-z]{2})(了?)', str(source))
    if (row is None or row.get('status') != 'confirmed' or row.get('ambiguous')
            or short is None or not _LATIN_IDENTIFIER.fullmatch(str(target))
            or sum(c.isalpha() for c in target) < 2
            or not ('glossary' in basis.lower() or '词库' in basis)
            or not ('context' in basis.lower() or '语境' in basis)):
        return False
    token, particle = short.groups()
    # This exception is for truncated IDs in Chinese commentary. An English
    # conjunction cannot borrow authority from player mentions elsewhere.
    if not re.search(r'[\u4e00-\u9fff]', cue_text):
        return False
    if any(x.get('canonical', '').casefold() == token.casefold()
           and x.get('canonical') != target for x in candidates):
        return False
    if not any(m.group() == token for m in _LATIN_TOKEN.finditer(cue_text)) or cue_text.count(source) != 1:
        return False
    heard = {m.group().casefold() for m in _LATIN_TOKEN.finditer(moss_text)
        if m.group().casefold().startswith(token.casefold())
        and latin_identifier_similarity(m.group(), target) >= .90}
    if len(heard) != 1:
        return False
    heard_token = next(iter(heard))
    matches = row.get('matches', ())
    if not any(m.get('cue_id') == cue_id and m.get('asr_source') == 'moss_text'
               and m.get('heard') == heard_token and m.get('score', 0) >= .90 for m in matches):
        return False
    repeated_ids = {m['cue_id'] for m in matches
        if isinstance(m.get('cue_id'), int) and m['cue_id'] != cue_id
        and abs(m['cue_id'] - cue_id) <= 20 and m.get('asr_source') in ('text', 'moss_text')
        and m.get('method') in ('exact', 'latin_identifier') and m.get('score', 0) >= .90}
    if len(repeated_ids) < 2:
        return False
    if particle:
        normalized_moss = _LATIN_TOKEN.sub(
            lambda m: target if m.group().casefold() == heard_token else m.group(), moss_text)
        proposed = cue_text.replace(source, target, 1)
        if ''.join(proposed.split()).casefold() != ''.join(normalized_moss.split()).casefold():
            return False
    return True


def contextual_patch_supported(source, target, basis, candidates, independent_sources, cue_id=None, cue_text=''):
    """Allow a model's local suggestion only with sent catalog+ASR evidence.

    Reference catalog status remains reference. Two independent ASR families
    must support the pronunciation; ambiguous candidates and common single
    characters cannot gain authority from glossary proximity.
    """
    row = next((x for x in candidates if x.get('canonical') == target), None)
    if row is None or row.get('ambiguous'):
        return False
    if latin_identifier_patch_supported(source, target, basis, candidates, cue_id, cue_text):
        return True
    # The actual provider can cite moss+qwen3+context for a catalog name. The
    # model's label is neither confirmation nor proof; sent catalog identity
    # and the independent evidence below are still mandatory.
    if not ('context' in basis.lower() or '语境' in basis):
        return False
    left, right = content(source), content(target)
    if not 2 <= len(left) == len(right) <= 8:
        return False
    if left[:1] in '的了着地得' and left[:1] != right[:1]:
        return False
    threshold = 1.0 if len(right) == 2 else .90 if len(right) == 3 else .94
    if not any(x.get('cue_id') == cue_id and x.get('asr_source') == 'text'
               and x.get('heard') == left and x.get('score', 0) >= threshold for x in row.get('matches', ())):
        return False
    # A two-character window such as 对「阵赤」心勇士 can sound exactly like
    # 振翅 while crossing a longer retrieved name. Do not authorize fragments
    # cut out of another local term merely because their sounds agree.
    cue = content(cue_text)
    if cue and cue.count(left) == 1:
        a, b = cue.index(left), cue.index(left)+len(left)
        for other in candidates:
            if other is row:
                continue
            for match in other.get('matches', ()):
                heard = match.get('heard', '')
                if (match.get('cue_id') != cue_id or match.get('asr_source') != 'text'
                        or len(heard) <= len(left)):
                    continue
                for occurrence in re.finditer(re.escape(heard), cue):
                    x, y = occurrence.span()
                    if a < y and x < b:
                        return False
    wanted = phonetic_text(right)
    families = set()
    for family, value in independent_sources:
        text = content(value)
        for start in range(max(0, len(text)-len(right)+1)):
            heard = text[start:start+len(right)]
            if SequenceMatcher(None, wanted, phonetic_text(heard), autojunk=False).ratio() >= threshold:
                families.add(family)
                break
    return len(families) >= 2


def pending_identifier_suggestions(text, candidates, cue_id):
    """Report recalled typo tokens that still need review after a valid call.

    A successful JSON request says nothing about whether a recalled name was
    used. This readonly receipt is deliberately separate from call success.
    """
    tokens = {m.group().casefold() for m in _LATIN_TOKEN.finditer(str(text))}
    pending = []
    for row in candidates:
        for match in row.get('matches', ()):
            heard = match.get('heard', '')
            if match.get('method') == 'single_hanzi_weak':
                # Old retrieval caches cannot resurrect isolated-syllable advice.
                continue
            if (match.get('cue_id') != cue_id or match.get('asr_source') != 'text'
                    or match.get('method') != 'latin_identifier'
                    or heard not in tokens or heard == row['canonical'].casefold()):
                continue
            suggestion = {'source': heard, 'canonical': row['canonical'],
                'status': row.get('status'), 'ambiguous': bool(row.get('ambiguous')),
                'reason': 'recalled_candidate_not_adopted', 'acoustic_verified': False}
            if suggestion not in pending:
                pending.append(suggestion)
    return pending
