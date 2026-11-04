"""Actual 2026-10-05 GE task proposals, replayed without a new provider call."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_stage9_cache_and_budget import context
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry, TermResolver, remap_words


def data():
    return json.loads((Path(__file__).parent/'fixtures/ge_edg_terminology_replay.json').read_text('utf8'))


def rows():
    return [SpeechSegment(**row, words=[]) for row in data()['segments']]


def snapshot():
    return GlossarySnapshot.from_dict(data()['snapshot'])


def proposals():
    return [{'id': int(ident), 'edits': edits} for ident, edits in data()['returned_edits'].items()]


def test_actual_snapshot_and_recall_preserve_missing_terms():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    catalog = snapshot()
    assert TermResolver(catalog).effective_term_count == 86
    assert 'Stew' in catalog.canonical_terms and 'CHICHOO' in catalog.canonical_terms
    assert not {'autumn', 'Smoggy', 'PatMen'} & set(catalog.canonical_terms)
    assert not any('球球' in entry.aliases for lib in catalog.libraries for entry in lib.terms)
    found = retrieve_candidates(catalog, rows())
    stew = next(row for row in found if row['canonical'] == 'Stew')
    assert any(m['cue_id'] == 37 and m['method'] == 'reference_bridge' for m in stew['matches'])
    assert any(m['cue_id'] == 38 and m['method'] == 'batch_entity_bridge' for m in stew['matches'])
    assert any(row['canonical'] == 'CHICHOO' and row['weak_only'] for row in found)


def test_actual_three_proposals_enter_production_safety(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = snapshot()
    source = rows()
    def complete(messages, **kwargs):
        body = json.loads(messages[1]['content'])
        assert body['terminology_retrieval']['effective_terms'] == 86
        return json.dumps({'checked_ids': [x.segment_id for x in source], 'cues': proposals()}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    result = polishing.call_correction_api(source, [], '', '', 'GE vs EDG', '', [], [], [],
        glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[37] == 'Stew点掉了一个'
    assert result[38] == 'panda也收掉了Stew'
    assert result[22] == '大部队已经在往A点退防了'
    assert source[36].caption_arbitration['terminology_polish']['accepted_edits'][0]['rule_id'] == 'confirmed_id_reference_bridge'
    assert source[37].caption_arbitration['terminology_polish']['accepted_edits'][0]['rule_id'] == 'confirmed_id_batch_entity_bridge'
    assert not source[36].caption_arbitration['terminology_polish']['rejected_edits']
    assert result[43] == source[42].text  # No guessed Chinese alias mapping.


@pytest.mark.parametrize('mutate,rule', [
    ('unconfirmed', 'catalog_without_local_support'),
    ('ambiguous', 'catalog_without_local_support'),
    ('derived_only', 'catalog_without_local_support'),
    ('overlap', 'overlapping_speaker_protection'),
    ('numbers', 'ordered_numeric_events_changed'),
])
def test_risky_counterexamples_are_explained(mutate, rule):
    import subtitle_core
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    source = rows()
    candidates = retrieve_candidates(snapshot(), source)
    if mutate == 'unconfirmed':
        for row in candidates: row['status'] = 'reference'
    elif mutate == 'ambiguous':
        for row in candidates: row['ambiguous'] = True
    elif mutate == 'derived_only':
        for row in candidates:
            row['matches'] = [m for m in row['matches'] if m.get('method') not in ('reference_bridge', 'batch_entity_bridge')]
    text = 'stu点掉了一个' if mutate != 'numbers' else 'stu打了20 20发'
    edit = {'from': 'stu', 'to': 'Stew', 'basis': 'glossary+context'}
    if mutate == 'numbers': edit = {'from': '20 20', 'to': '2020', 'basis': 'context'}
    decisions = []
    result, applied = apply_correction_edits(text, ['stw点掉了一个'], [edit],
        independent_sources=[('firered', 'stw点掉了一个')], contextual_term_candidates=candidates,
        cue_id=37, protect_primary_speaker=mutate == 'overlap', decisions=decisions)
    assert result == text and not applied
    assert decisions[0]['rule_id'] == rule


def test_spelling_context_does_not_authorize_an_intentional_repeat():
    import subtitle_core
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    text = '再往前走一步'
    decisions = []
    result, applied = apply_correction_edits(text, [], [{'from': '再往', 'to': '在往', 'basis': 'context'}],
        independent_sources=[], decisions=decisions)
    assert result == text and not applied
    assert decisions[0]['rule_id'] == 'local_difference_without_two_sources'


def test_bridge_cannot_authorize_a_changed_text_or_other_scope():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.glossary.terminology_support import confirmed_patch_evidence
    candidates = retrieve_candidates(snapshot(), rows())
    assert confirmed_patch_evidence('stu', 'Stew', 'glossary+context', candidates,
        37, 'stu现在去另一边') is None
    assert confirmed_patch_evidence('stu', 'Stew', 'glossary+context', candidates,
        99, 'stu点掉了一个') is None


@pytest.mark.parametrize('reference', ['panda也收掉了PatMen', 'panda也收掉了，PatMen', 'panda也收掉PatMen'])
def test_batch_bridge_cannot_override_current_asr_counterevidence(reference):
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.glossary.terminology_support import confirmed_patch_evidence
    source = rows()
    source[37].moss_text = source[37].text
    source[37].qwen_asr_text = reference
    source[37].firered_text = 'panda也收掉了st'
    candidates = retrieve_candidates(snapshot(), source)
    assert confirmed_patch_evidence('stu', 'Stew', 'glossary+context', candidates,
        38, source[37].text) is None


def test_same_cue_bridge_cannot_override_two_explicit_asr_counterexamples():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.glossary.terminology_support import confirmed_patch_evidence
    source = rows()
    source[36].moss_text = source[36].qwen_asr_text = 'PatMen点掉了一个'
    candidates = retrieve_candidates(snapshot(), source)
    assert confirmed_patch_evidence('stu', 'Stew', 'glossary+context', candidates,
        37, source[36].text) is None
    assert confirmed_patch_evidence('stu', 'Stew', 'glossary+context', candidates,
        38, source[37].text) is None


def test_word_remap_keeps_outer_edges_and_marks_derived_spans():
    row = rows()[36]
    words = [WordUnit(**w) for w in data()['words37']]
    result = remap_words(row.text, 'Stew点掉了一个', words, row.start, row.end, row.confidence)
    assert ''.join(x.text for x in result) == 'Stew点掉了一个'
    assert min(w.start for w in result) == row.start and max(w.end for w in result) == row.end
    assert all(row.start <= w.start <= w.end <= row.end for w in result)
    assert next(w for w in result if 'ew' in w.text).start == words[2].start


def test_names_and_enabled_aliases_are_not_split(context):
    import subtitle_core
    from twobyteasr.subtitle_rules.segmentation import repair_lexical_boundary_offsets, lexical_forbidden_boundary_offsets
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('v','词库','1',
        (TermEntry('CHICHOO', ('球球',)), TermEntry('BerLIN'), TermEntry('S0PP'), TermEntry('Zhe'))),))
    text = '这分其实完全没有商量好球球到了一个什么样的位置'
    row = SpeechSegment(1, 0, 5, text, .8, [])
    inside = text.index('球球')+1
    assert inside in lexical_forbidden_boundary_offsets(text)
    repaired = repair_lexical_boundary_offsets([row], [inside, len(text)])
    assert inside not in repaired
    assert ''.join(text[a:b] for a,b in zip([0]+repaired[:-1], repaired)) == text
    assert TermResolver(owner.glossary_snapshot).resolve('球球 BerLIN S0PP Zhe').text == 'CHICHOO BerLIN S0PP Zhe'


def test_reduplicated_entity_surface_kept_without_guessing_a_mapping(context):
    import subtitle_core
    from twobyteasr.subtitle_rules.segmentation import repair_lexical_boundary_offsets
    _, owner, _ = context
    owner.enable_domain_terms = False
    owner.glossary_snapshot = GlossarySnapshot(())
    text = '这分其实完全没有商量好球球到了一个什么样的位置'
    inside = text.index('球球')+1
    row = SpeechSegment(1, 0, 5, text, .8, [])
    assert inside not in repair_lexical_boundary_offsets([row], [inside, len(text)])
