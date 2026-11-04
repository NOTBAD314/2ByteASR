"""Retained real failures; provider replay is distinct from live AI acceptance."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_stage9_cache_and_budget import context
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry, TermResolver


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/valorant_real_terminology_failure.json').read_text('utf8'))


def snapshot(names=None):
    return GlossarySnapshot((GlossaryLibrary('real-fixture', '瓦罗兰特', 'canonical-only',
        tuple(TermEntry(x) for x in (names or fixture()['canonical_terms']))),))


def rows():
    return [SpeechSegment(**{'segment_id':x['id'], 'words':[],
        **{k:v for k,v in x.items() if k not in ('id','prior_model_edits','prior_rejected_edits')}})
        for x in fixture()['rows']]


def test_canonical_only_real_recall_uses_complete_latin_tokens():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    source = rows()
    catalog = snapshot()
    assert all(not term.aliases for library in catalog.libraries for term in library.terms)
    found = retrieve_candidates(catalog, source)
    by_name = {x['canonical']:x for x in found}
    assert any(m['cue_id']==4 and m['asr_source']=='text' and m['heard']=='borlin'
        for m in by_name['BerLIN']['matches'])
    for ident in (10,13,22,24):
        assert any(m['cue_id']==ident and m['asr_source']=='text' and m['heard']=='sop'
            for m in by_name['S0pp']['matches'])
    assert not any(m['cue_id']==8 and m['asr_source']=='text' for m in by_name['S0pp']['matches'])
    weapon = GlossarySnapshot((GlossaryLibrary('weapon','武器','1',(TermEntry('冥驹',('op',)),)),))
    assert retrieve_candidates(weapon,[source[-1]]) == []
    assert TermResolver(catalog).resolve('Borlin Sop 折 So').text == 'Borlin Sop 折 So'


def test_replayed_retained_provider_proposals_pass_safety_and_keep_case(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = snapshot()
    source = rows()
    actual_proposals = [{'id':x['id'],'edits':x['prior_model_edits']} for x in fixture()['rows']
        if x['prior_model_edits']]
    def complete(messages, **kwargs):
        body = json.loads(messages[1]['content'])
        assert {'BerLIN','S0pp'} <= set(body['enabled_glossary_evidence']['canonical_terms'])
        return json.dumps({'checked_ids':[x.segment_id for x in source],'cues':actual_proposals},ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    result = polishing.call_correction_api(source,[],'','','真实原稿','瓦罗兰特',[],[],[],
        glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[4] == 'BerLIN也没有接住'
    assert result[22] == '这确实是S0pp的风格'
    assert result[24] == '就S0pp的反应不是说'
    # Real response did not propose these two fixes. Replay cannot call them
    # successful AI corrections merely because recall now contains the term.
    assert result[10] == '要终结比赛了sop' and result[13] == 'Sop这个多杀'
    assert result[6] == '折也没有了' and result[8] == 'So了还在往里走'
    assert not source[0].caption_arbitration['terminology_polish']['rejected_edits']
    assert source[0].caption_arbitration['terminology_polish']['accepted_edits'][0]['model_to']=='berlin'


@pytest.mark.parametrize('text,edit',[
    ('折也没有了',{'from':'折','to':'Zhe','basis':'glossary+context'}),
    ('So了还在往里走',{'from':'So','to':'S0pp','basis':'glossary+context'}),
    ('Borlin也没有接住',{'from':'Borlin','to':'BerLIN','basis':'model knowledge'}),
    ('prefixBorlin也没有接住',{'from':'Borlin','to':'BerLIN','basis':'glossary+context'}),
])
def test_text_context_does_not_authorize_ambiguous_or_fragment_edits(text,edit):
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    row = SpeechSegment(77,0,1,text,.85,[])
    candidates = retrieve_candidates(snapshot(),[row])
    final, accepted = apply_correction_edits(text,[],[edit],independent_sources=[],
        contextual_term_candidates=candidates,cue_id=77)
    assert final == text and accepted == []


def test_similar_enabled_names_are_ambiguous_and_existing_name_is_preserved():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    row = SpeechSegment(77,0,1,'Borlin也没有接住',.85,[])
    candidates = retrieve_candidates(snapshot(['BerLIN','Barlin']),[row])
    assert all(x['ambiguous'] for x in candidates)
    text, accepted = apply_correction_edits(row.text,[],[
        {'from':'Borlin','to':'BerLIN','basis':'glossary+context'}],independent_sources=[],
        contextual_term_candidates=candidates,cue_id=77)
    assert text == row.text and accepted == []


def test_only_polish_cache_changes_for_case_alias_or_revision(context, monkeypatch):
    from twobyteasr.recognition import cache
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = snapshot(['berlin','s0pp','zhe'])
    stages=('audio','firered_vad','moss','firered','firered_primary','polished')
    before={stage:cache.cache_stage_signature(stage) for stage in stages}
    owner.glossary_snapshot = snapshot()
    after={stage:cache.cache_stage_signature(stage) for stage in stages}
    assert after['polished'] != before['polished']
    assert all(after[s]==before[s] for s in stages if s!='polished')
    frozen=after['polished']
    original_digest=cache.file_digest
    monkeypatch.setattr(cache,'file_digest',lambda path:'edited-live-db' if path in
        (cache.LEARNED_TERMS_PATH,cache.GAME_PROFILES_PATH) else original_digest(path))
    assert cache.cache_stage_signature('polished') == frozen
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('real-fixture','瓦罗兰特','new-revision',
        (TermEntry('BerLIN',('明确测试别名',)),TermEntry('S0pp'),TermEntry('Zhe'))),))
    assert cache.cache_stage_signature('polished') != frozen


def test_full_polish_cache_reuses_call_and_records_unadopted_real_names(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, cache = context
    owner.enable_domain_terms=True
    owner.glossary_snapshot=snapshot()
    monkeypatch.setattr(polishing,'discover_global_domain_term_mappings',lambda *a:[])
    actual=[x for x in rows() if x.segment_id in (4,10,13)]
    count=[]
    def complete(messages, **kwargs):
        count.append(1)
        return json.dumps({'checked_ids':[x.segment_id for x in actual],'cues':[{'id':4,'edits':[
            {'from':'Borlin','to':'BerLIN','basis':'glossary+context'}]}]},ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    for attempt in range(2):
        result=polishing.polish_subtitles(copy.deepcopy(actual),'真实原稿',cache)
        assert result[0].text=='BerLIN也没有接住'
        for cue in result[1:]:
            receipt=cue.caption_arbitration['terminology_polish']
            assert receipt['response_state']=='validated' and receipt['quality_state']=='term_review_needed'
            assert receipt['candidate_usage']['unresolved_candidates'][0]['canonical']=='S0pp'
    assert count==[1]


def test_confirmed_mapping_remains_separate_offline_rule():
    from twobyteasr.glossary.terminology import snapshot_from_pairs
    explicit=snapshot_from_pairs([('错写ID','Exact0Name'),('错误中文','正确中文')])
    assert TermResolver(explicit).resolve('错写ID和错误中文').text=='Exact0Name和正确中文'
    assert not snapshot().libraries[0].terms[0].aliases


def test_rejected_ambiguous_model_name_retains_text_and_open_quality_review(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms=True
    owner.glossary_snapshot=snapshot()
    source=next(x for x in rows() if x.segment_id==8)
    def complete(messages, **kwargs):
        return json.dumps({'checked_ids':[8],'cues':[{'id':8,'edits':[
            {'from':'So了','to':'S0pp','basis':'glossary+context'}]}]},ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    result=polishing.call_correction_api([source],[],'','','真实原稿','瓦罗兰特',[],[],[],
        glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[8]=='So了还在往里走'
    receipt=source.caption_arbitration['terminology_polish']
    assert receipt['response_state']=='validated' and receipt['quality_state']=='pending_rejected_edit_review'
    assert receipt['rejected_edit_count']==1 and not receipt['accepted_edits']
