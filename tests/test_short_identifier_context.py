"""Current production proposals replayed locally; no live provider request."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_stage9_cache_and_budget import context
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry, TermResolver
from twobyteasr.glossary.terminology_retrieval import (
    retrieve_candidates, short_latin_identifier_patch_supported, pending_identifier_suggestions,
)


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/valorant_current_short_identifier_failure.json').read_text('utf8'))


def snapshot(names=None):
    return GlossarySnapshot((GlossaryLibrary('current-fixture', '瓦罗兰特', 'canonical-only',
        tuple(TermEntry(x) for x in (names or fixture()['canonical_terms']))),))


def rows():
    return [SpeechSegment(segment_id=x['id'], words=[], **{k:v for k,v in x.items()
        if k not in ('id', 'production_returned_edits', 'production_rejected_edits')})
        for x in fixture()['rows']]


def replay_provider(monkeypatch, calls):
    actual = fixture()['rows']
    def complete(messages, **kwargs):
        body = json.loads(messages[1]['content'])
        calls.append(body)
        return json.dumps({'checked_ids':[x['id'] for x in body['cues']],
            'cues':[{'id':x['id'], 'edits':x['production_returned_edits']}
                    for x in actual if x['id'] in {c['id'] for c in body['cues']}]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
        lambda *a, **k: SimpleNamespace(complete=complete))


def enable_current_game(context):
    from twobyteasr.recognition.run_context import sync_legacy_runtime
    core, owner, cache = context
    owner.game_name = '瓦罗兰特'
    owner.enable_domain_terms = True
    owner.glossary_snapshot = snapshot()
    sync_legacy_runtime(core, owner)
    return owner, cache


def test_current_real_rejected_proposal_passes_only_with_same_cue_moss_and_repeats(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    owner, _ = enable_current_game(context)
    calls = []
    replay_provider(monkeypatch, calls)
    source = rows()
    result = polishing.call_correction_api(source, [], '', '', '当前真实片段', '瓦罗兰特', [], [], [],
        glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[8] == 'S0pp还在往里走'
    receipt = next(x for x in source if x.segment_id == 8).caption_arbitration['terminology_polish']
    assert receipt['accepted_edits'][0]['from'] == 'So了'
    assert receipt['accepted_edits'][0]['terminology_evidence']['basis'] == 'model_glossary_context_and_same_cue_moss_repeated_ids'
    assert not receipt['accepted_edits'][0]['terminology_evidence']['acoustic_verified']
    assert not receipt['rejected_edits']
    assert all(not term.aliases for lib in owner.glossary_snapshot.libraries for term in lib.terms)
    assert TermResolver(owner.glossary_snapshot).resolve('折 So Sop').text == '折 So Sop'
    for ident, expected in [(6, '折也没有了'), (7, '折马了')]:
        assert result[ident] == expected
        detail = next(x for x in source if x.segment_id == ident).caption_arbitration['terminology_polish']
        assert detail['quality_state'] == 'term_review_needed'
        assert detail['candidate_usage']['unresolved_candidates'][0]['canonical'] == 'Zhe'
        assert detail['sent_candidates'][0]['weak_only']


@pytest.mark.parametrize('mutation', ['no_moss', 'no_repeats', 'one_repeat', 'duplicate_family_cue',
    'wrong_sentence', 'ordinary_english', 'different_enabled_name', 'model_knowledge', 'ambiguous'])
def test_short_id_evidence_cannot_be_borrowed_or_delete_unmatched_words(mutation):
    source = rows()
    cue = next(x for x in source if x.segment_id == 8)
    catalog = snapshot()
    basis = 'glossary+context'
    if mutation == 'no_moss': cue.moss_text = ''
    if mutation == 'no_repeats': source = [cue]
    if mutation == 'one_repeat': source = [cue, next(x for x in source if x.segment_id == 10)]
    if mutation == 'duplicate_family_cue':
        other = next(x for x in source if x.segment_id == 10)
        source = [cue, other, copy.deepcopy(other)]
    if mutation == 'wrong_sentence': cue.moss_text = 'Sop还在往外走'
    if mutation == 'ordinary_english':
        cue.text = 'So this is ordinary English'
        cue.moss_text = 'Sop this is ordinary English'
    if mutation == 'different_enabled_name': catalog = snapshot(['So', 'S0pp'])
    if mutation == 'model_knowledge': basis = 'model knowledge'
    candidates = retrieve_candidates(catalog, source)
    if mutation == 'ambiguous':
        next(x for x in candidates if x['canonical'] == 'S0pp')['ambiguous'] = True
    edit = 'So' if mutation == 'ordinary_english' else 'So了'
    assert not short_latin_identifier_patch_supported(edit, 'S0pp', basis, candidates,
        cue.segment_id, cue.text, cue.moss_text)


@pytest.mark.parametrize('text,edit,moss', [
    ('折叠好了', {'from':'折','to':'Zhe','basis':'glossary+context'}, '折叠好了'),
    ('这个打折了', {'from':'折','to':'Zhe','basis':'glossary+context'}, '这个打折了'),
    ('折返再继续', {'from':'折','to':'Zhe','basis':'glossary+context'}, '折返再继续'),
    ('这也没有了', {'from':'这','to':'Zhe','basis':'glossary+context'}, '这也没有了'),
    ('so我们继续', {'from':'so','to':'S0pp','basis':'glossary+context'}, 'so我们继续'),
    ('So这边还有两个人', {'from':'So两','to':'S0pp','basis':'glossary+context'}, 'Sop这边还有两个人'),
    ('So了还在往里走', {'from':'So了还在','to':'S0pp','basis':'glossary+context'}, 'Sop还在往里走'),
])
def test_ordinary_chinese_and_english_stay_unchanged_even_with_real_neighbor_ids(text, edit, moss):
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    cue = SpeechSegment(8, 0, 1, text, .8, [], moss_text=moss, firered_text=text, qwen_asr_text=text)
    neighbors = [x for x in rows() if x.segment_id != 8]
    candidates = retrieve_candidates(snapshot(), [cue, *neighbors])
    final, accepted = apply_correction_edits(text, [text, text], [edit],
        independent_sources=[('firered', text), ('qwen', text)],
        contextual_term_candidates=candidates, cue_id=8, moss_text=moss)
    assert final == text and accepted == []
    assert pending_identifier_suggestions(final, candidates, 8) == []


def test_full_pipeline_retains_short_id_patch_with_derived_timing_and_batch_cache(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    owner, cache = enable_current_game(context)
    monkeypatch.setattr(polishing, 'discover_global_domain_term_mappings', lambda *a: [])
    calls = []
    replay_provider(monkeypatch, calls)
    for _ in range(2):
        result = polishing.polish_subtitles(copy.deepcopy(rows()), '当前真实片段', cache)
        cue = next(x for x in result if x.segment_id == 8)
        assert cue.text == cue.final_text == 'S0pp还在往里走'
        assert not cue.caption_arbitration['terminology_polish']['final_filter_changed']
        assert cue.caption_arbitration['terminology_normalization'][-1]['requires_acoustic_alignment']
        assert next(x for x in result if x.segment_id == 6).text == '折也没有了'
        assert next(x for x in result if x.segment_id == 6).caption_arbitration['terminology_polish']['quality_state'] == 'term_review_needed'
    assert len(calls) == 1
    assert '瓦罗兰特' in calls[0]['project_context']


def test_short_id_support_does_not_override_primary_speaker_overlap_protection():
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    source = rows()
    cue = next(x for x in source if x.segment_id == 8)
    candidates = retrieve_candidates(snapshot(), source)
    edit = fixture()['rows'][2]['production_returned_edits']
    assert short_latin_identifier_patch_supported('So了', 'S0pp', 'glossary+context',
        candidates, 8, cue.text, cue.moss_text)
    final, accepted = apply_correction_edits(cue.text, [], edit,
        independent_sources=[], contextual_term_candidates=candidates,
        cue_id=8, moss_text=cue.moss_text, protect_primary_speaker=True)
    assert final == cue.text and accepted == []


def test_rule_version_invalidates_polish_without_invalidating_asr(context, monkeypatch):
    from twobyteasr.recognition import cache
    from twobyteasr.glossary import terminology_retrieval
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = snapshot()
    stages = ('audio', 'firered_vad', 'moss', 'firered', 'firered_primary', 'polished')
    current = {s:cache.cache_stage_signature(s) for s in stages}
    monkeypatch.setattr(terminology_retrieval, 'RULE_VERSION', 'glossary-context-recall-v4-latin-token')
    old = {s:cache.cache_stage_signature(s) for s in stages}
    assert current['polished'] != old['polished']
    assert all(current[s] == old[s] for s in stages if s != 'polished')
