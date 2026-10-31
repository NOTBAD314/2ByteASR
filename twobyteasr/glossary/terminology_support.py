"""Bounded catalog normalization evidence, independent of optional web search."""
from __future__ import annotations

import re
from ..subtitle_rules.text_similarity import levenshtein

TOKEN = re.compile(r'(?<![A-Za-z0-9_])[A-Za-z0-9_]+(?![A-Za-z0-9_])')
ASR_FIELDS = ('moss_text', 'firered_text', 'qwen_asr_text')
# Game words every Chinese stream uses; never a player or creature ID.
COMMON_GAME_WORDS = frozenset({'buff', 'debuff', 'nerf', 'pvp', 'pve', 'npc', 'boss', 'mvp', 'dps', 'aoe'})


def _bridge_shape(source, heard, canonical):
    """A near canonical reference may anchor a different bounded primary typo."""
    values = [str(x).casefold() for x in (source, heard, canonical)]
    if not all(re.fullmatch(r'[a-z]{3,16}', x) for x in values):
        return False
    source, heard, canonical = values
    return (source[:2] == heard[:2] == canonical[:2]
            and levenshtein(source, heard) <= 1
            and levenshtein(source, canonical) <= 2
            and abs(len(source)-len(canonical)) <= 1)


def _local_reference_tokens(cue_text, source, reference):
    """Identify the token in the same grammatical slot, not another player."""
    compact = lambda text: re.sub(r'[^\w\u4e00-\u9fff]', '', str(text)).casefold()
    cue, ref = compact(cue_text), compact(reference)
    matches = [m for m in TOKEN.finditer(cue) if m.group() == source.casefold()]
    if len(matches) != 1:
        return []
    span = matches[0]
    # Optional aspect particles and punctuation may differ between models.
    # Retain two lexical neighbours so an explicitly different ID in the same
    # slot vetoes a cross-cue bridge even when one model omits "了".
    left_context = lambda text, end: text[max(0, end-5):end].rstrip('了')[-2:]
    left, right = left_context(cue, span.start()), cue[span.end():span.end()+2]
    output = []
    for token in TOKEN.finditer(ref):
        before, after = left_context(ref, token.start()), ref[token.end():token.end()+2]
        if ((len(left) == 2 and left == before) or (len(right) == 2 and right == after)):
            output.append(token.group())
    return output


def _current_reference_support(segment, source, canonical, heard):
    evidence, opposed = [], []
    for field in ASR_FIELDS:
        for token in _local_reference_tokens(segment.text, source, getattr(segment, field, '')):
            match = {'asr_source': field, 'heard': token}
            if len(token) < 3:
                # A truncated two-letter reference neither proves a complete
                # competing entity nor supplies an independent full-ID vote.
                if source.casefold().startswith(token) and canonical.casefold().startswith(token):
                    evidence.append({**match, 'support_kind': 'partial_identifier_only'})
                continue
            if (token == source.casefold() or token == canonical.casefold()
                    or _bridge_shape(token, heard, canonical)):
                evidence.append(match)
            else:
                opposed.append(match)
    return evidence, opposed


def enrich_reference_bridges(rows, segments):
    """Retain same-cue ASR anchors and bounded repeated mentions in this batch.

    This supplies candidate evidence only. A model must still propose the edit,
    and the adjudicator must validate its catalog status, ambiguity and scope.
    No aliases are written to the user's library.
    """
    by_id = {s.segment_id: s for s in segments}
    bridges = []
    enabled_names = {r['canonical'].casefold() for r in rows}
    for row in rows:
        if row.get('status') != 'confirmed':
            continue
        for match in list(row.get('matches', ())):
            segment = by_id.get(match.get('cue_id'))
            field = match.get('asr_source')
            if segment is None or field not in ASR_FIELDS or match.get('score', 0) < .80:
                continue
            ref = str(getattr(segment, field, ''))
            heard = match['heard']
            heard_tokens = [m.group() for m in TOKEN.finditer(ref) if m.group().casefold() == heard]
            if len(heard_tokens) != 1:
                continue
            for token in TOKEN.finditer(str(segment.text)):
                source = token.group()
                if source.casefold() in enabled_names and source.casefold() != row['canonical'].casefold():
                    continue
                if not _bridge_shape(source, heard, row['canonical']):
                    continue
                # Match complete local statements after replacing only the ID.
                normalize = lambda text: ''.join(str(text).split()).casefold()
                if normalize(str(segment.text).replace(source, row['canonical'], 1)) != normalize(
                        TOKEN.sub(lambda m: row['canonical'] if m.group().casefold() == heard else m.group(), ref)):
                    continue
                support, opposition = _current_reference_support(segment, source, row['canonical'], heard)
                if opposition:
                    continue
                evidence = {'cue_id': segment.segment_id, 'asr_source': 'text',
                    'heard': source.casefold(), 'score': match['score'], 'method': 'reference_bridge',
                    'matched_text': segment.text,
                    'current_reference_support': support,
                    'anchor': {'cue_id': segment.segment_id, 'asr_source': field, 'heard': heard,
                               'primary_text': segment.text, 'reference_text': ref}}
                if evidence not in row['matches']:
                    row['matches'].append(evidence)
                bridges.append((row, source.casefold(), evidence))
    for row, source, evidence in bridges:
        for segment in segments:
            if (segment.segment_id == evidence['cue_id']
                    or abs(segment.segment_id-evidence['cue_id']) > 20
                    or not re.search(r'[\u4e00-\u9fff]', str(segment.text))):
                continue
            tokens = [m.group().casefold() for m in TOKEN.finditer(str(segment.text))]
            if tokens.count(source) != 1:
                continue
            support, opposition = _current_reference_support(segment, source, row['canonical'],
                evidence['anchor']['heard'])
            if not support or opposition:
                continue
            item = {'cue_id': segment.segment_id, 'asr_source': 'text', 'heard': source,
                    'score': evidence['score'], 'method': 'batch_entity_bridge',
                    'matched_text': segment.text,
                    'current_reference_support': support,
                    'anchor': evidence['anchor']}
            if item not in row['matches']:
                row['matches'].append(item)


def confirmed_patch_evidence(source, target, basis, candidates, cue_id, cue_text, span=None):
    row = next((r for r in candidates if r.get('canonical') == target), None)
    basis = str(basis).lower()
    if (not row or row.get('status') != 'confirmed' or row.get('ambiguous')
            or not ('glossary' in basis or '词库' in basis)
            or not ('context' in basis or '语境' in basis)
            or source not in str(cue_text)):
        return None
    if any(r.get('canonical', '').casefold() == source.casefold()
           and r.get('canonical') != target for r in candidates):
        return None
    if source in row.get('aliases', ()):
        from ..recognition.content_scene import alias_context_conflict
        if alias_context_conflict(cue_text, source, target,
                category=' '.join(str(s.get('category', '')) for s in row.get('sources', ())), span=span):
            return None
        return {'rule_id': 'confirmed_exact_alias', 'canonical': target, 'alias': source,
                'acoustic_verified': False}
    if not any(m.group() == source for m in TOKEN.finditer(str(cue_text))):
        return None
    for match in row.get('matches', ()):
        anchor = match.get('anchor', {})
        if (match.get('cue_id') == cue_id and match.get('heard') == source.casefold()
                and match.get('method') in ('reference_bridge', 'batch_entity_bridge')
                and ''.join(str(cue_text).split()).casefold() == ''.join(str(match.get('matched_text', '')).split()).casefold()
                and anchor.get('asr_source') in ASR_FIELDS
                and _bridge_shape(source, anchor.get('heard', ''), target)):
            if match['method'] == 'batch_entity_bridge' and not match.get('current_reference_support'):
                continue
            return {'rule_id': 'confirmed_id_'+match['method'], 'canonical': target,
                    'source_token': source, 'anchor': dict(anchor),
                    'current_reference_support': match.get('current_reference_support', []),
                    'acoustic_verified': False}
    return None


def contextual_spelling_patch(source, target, basis, cue_text, start):
    """Aspect-marked ongoing movement, with no permission for free paraphrase."""
    if source != '再往' or target != '在往' or not ('context' in str(basis).lower() or '语境' in str(basis)):
        return False
    return bool(re.search(r'(已经|现在|目前|此时|这时)$', str(cue_text)[:start]))


def recall_gaps(segments, candidates, snapshot=None):
    """Unmatched ID-like surfaces are review signals, never guessed mappings."""
    # A gap is relative to an enabled glossary. With none selected, ordinary
    # English words used to create hundreds of spurious review obligations.
    # Other ASR conflicts and explicit model suggestions have their own paths;
    # do not erase persisted review evidence or alter the transcript here.
    if snapshot is not None and not snapshot.libraries:
        return []
    output = []
    from ..subtitle_rules.language_rules import active_task_language
    from ..subtitle_rules.correction_risk import SPACED_LANGUAGES
    natural_spaced_language = active_task_language() in SPACED_LANGUAGES
    exact_index = {}
    for library in getattr(snapshot, 'libraries', ()):
        for term in library.terms:
            for spelling in (term.canonical, *term.aliases):
                exact_index.setdefault(spelling.casefold(), []).append({
                    'library_id': library.id, 'revision': library.revision,
                    'canonical': term.canonical, 'confirmed': term.confirmed,
                    'matched_alias': spelling != term.canonical})
    # Proper names can be ordinary Chinese spellings rather than Latin IDs or
    # repeated characters. POS tagging supplies review signals only; it never
    # guesses a canonical ID or authorizes a replacement.
    # 2026-10-28 (user's 20-minute and 1-hour streams, 22/45 and 64/100
    # review items): jieba's dictionary tags ordinary words as names (nr:
    # 阳光 安静 荣誉; nz: 聊天 世界观 普通). Person-name tags only, and not a
    # word as common as ordinary vocabulary.
    from ..subtitle_rules.stutter_cleanup import (ORDINARY_WORD_FREQ, ordinary_reduplication,
                                                  reduplication_names_nothing, word_frequency)
    proper = {}
    if snapshot is not None and snapshot.libraries and not natural_spaced_language:
        from jieba.posseg import cut
        proper = {segment.segment_id: {token.word for token in cut(str(segment.text), HMM=False)
            if token.flag in {'nr', 'nrfg', 'nrt'} and 2 <= len(token.word) <= 12
            and word_frequency(token.word) < ORDINARY_WORD_FREQ}
            for segment in segments}
    for segment in segments:
        surfaces = {m.group() for m in TOKEN.finditer(str(segment.text))
                    if len(m.group()) >= 3 and m.group().casefold() not in COMMON_GAME_WORDS}
        # A doubled nickname (\u7403\u7403) is a name signal; ordinary doubled words
        # (\u521a\u521a) and stammers (\u518d\u518d, \u8fd9\u8fd9) are not (2026-10-10, user report).
        surfaces.update(m.group() for m in re.finditer(r'([\u4e00-\u9fff])\1+', str(segment.text))
                        if not reduplication_names_nothing(str(segment.text), *m.span()))
        # jieba tags \u8c22\u8c22/\u5b9d\u5b9d as person names; doubled common words stay ordinary.
        surfaces.update(word for word in proper.get(segment.segment_id, ())
                        if not (len(set(word)) == 1 and ordinary_reduplication(word, 0, len(word))))
        for surface in sorted(surfaces):
            if any(r['canonical'].casefold() == surface.casefold()
                    or surface in r.get('aliases', ())
                    or any(m.get('cue_id') == segment.segment_id and m.get('heard') == surface.casefold()
                           for m in r.get('matches', ())) for r in candidates):
                continue
            exact = exact_index.get(surface.casefold(), [])
            # A glossary is not a dictionary of a whole spoken language.
            # Missing ordinary Latin words are retrieval diagnostics, never
            # thousands of suspects demanding one model receipt per word.
            if natural_spaced_language and not exact:
                continue
            output.append({'cue_id': segment.segment_id, 'surface': surface,
                'state': 'no_recalled_candidate', 'reason': 'missing_alias_or_enabled_term; no canonical inferred',
                'in_snapshot': bool(exact), 'exact_snapshot_entries': exact,
                'candidate_recalled': False, 'canonical_inferred': False})
    return output


def suspicious_spans(segments, candidates, gaps):
    """Positions needing semantic adjudication, including ordinary legal words."""
    by_id = {segment.segment_id: segment for segment in segments}
    positions = {}
    def add(cue_id, start, end, surface, reason, candidate=None, role='unknown'):
        if cue_id not in by_id or start is None or end is None:
            return
        key = (cue_id, start, end)
        row = positions.setdefault(key, {'suspect_id': f's{cue_id}:{start}:{end}',
            'cue_id': cue_id, 'start': start, 'end': end, 'surface': surface,
            'entity_role': role, 'reasons': [], 'candidate_ids': []})
        if reason not in row['reasons']:
            row['reasons'].append(reason)
        if candidate and candidate['candidate_id'] not in row['candidate_ids']:
            row['candidate_ids'].append(candidate['candidate_id'])
    for candidate in candidates:
        for match in candidate.get('matches', ()):
            if match.get('asr_source') != 'text' or match.get('cue_id') not in by_id:
                continue
            if match.get('method') == 'exact' and not match.get('matched_alias'):
                continue
            add(match['cue_id'], match.get('start'), match.get('end'), match['heard'],
                match['method'], candidate, match.get('entity_role') or
                next(iter(candidate.get('entity_types', ())), 'unknown'))
    for gap in gaps:
        text = str(by_id[gap['cue_id']].text)
        for occurrence in re.finditer(re.escape(gap['surface']), text, re.I):
            add(gap['cue_id'], *occurrence.span(), occurrence.group(), 'no_recalled_candidate')
    for segment in segments:
        for occurrence in re.finditer(r'交出(?:了)?(?P<object>[\u4e00-\u9fff]{2,4})', str(segment.text)):
            add(segment.segment_id, occurrence.start('object'), occurrence.end('object'),
                occurrence['object'], 'action_object_may_be_misheard', role='skill_or_item')
        for occurrence in re.finditer(r'(?P<id>[A-Za-z]{2,16})[\u4e00-\u9fff](?=交出)', str(segment.text)):
            add(segment.segment_id, occurrence.start(), occurrence.end(), occurrence.group(),
                'possible_identifier_boundary', role='player')
    roster = [row['candidate_id'] for row in candidates
        if 'player' in row.get('entity_types', ()) and any(
            match.get('method') == 'enabled_roster_context' for match in row.get('matches', ()))]
    for row in positions.values():
        if not row['candidate_ids'] and row['entity_role'] in ('unknown', 'player'):
            row['candidate_ids'] = list(roster)
            if roster:
                row['reasons'].append('enabled_entity_context_requires_evidence')
    return list(positions.values())
