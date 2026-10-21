"""Production glossary context, including a retained real user failure excerpt."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from tests.test_stage9_cache_and_budget import context
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry


def real_fixture():
    return json.loads((Path(__file__).parent / 'fixtures/rocom_real_context_failure.json').read_text('utf8'))


def real_cue():
    values = real_fixture()['asr']
    return SpeechSegment(segment_id=3, start=4.033, end=5.467, confidence=.86,
        primary_source='moss-host', speaker='S01', words=[], **values)


def test_real_wrong_chinese_names_retrieve_references_without_exact_source_spelling():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    fixture = real_fixture()
    snapshot = GlossarySnapshot.from_dict(fixture['snapshot'])
    candidates = retrieve_candidates(snapshot, [real_cue()])
    by_term = {row['canonical']: row for row in candidates}
    for name in ('仪式巨像', '炽心勇狮'):
        assert by_term[name]['status'] == 'reference'
        assert by_term[name]['sources'][0]['library_id'] == '洛克王国世界'
        assert any(match['cue_id'] == 3 for match in by_term[name]['matches'])
    assert fixture['source']['manually_corrected_text'] != real_cue().text
    assert len(candidates) < 85 + 1029


def test_actual_serialized_prompt_keeps_retrieved_nonliteral_references(context):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot.from_dict(real_fixture()['snapshot'])
    messages = polishing.call_correction_api([real_cue()], [], '', '', '洛克真实片段',
        '洛克王国：世界', [], [], [], glossary_evidence=owner.glossary_snapshot.evidence(), _messages_only=True)
    body = json.loads(messages[1]['content'])
    assert {'仪式巨像', '炽心勇狮'} <= set(body['glossary_reference'])
    assert all(row['status'] == 'reference' for row in body['terminology_candidates']
               if row['canonical'] in ('仪式巨像', '炽心勇狮'))
    assert 'read-only' in body['context_access']


def test_highly_related_last_entry_survives_budget_and_irrelevant_entries_do_not(context):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('fixture', '夹具', 'r1',
        tuple(TermEntry('完全无关词条' + str(i)) for i in range(180)), ('炽心勇狮',)),))
    messages = polishing.call_correction_api([real_cue()], [], '', '', '夹具', '夹具',
        [], [], [], glossary_evidence=owner.glossary_snapshot.evidence(), _messages_only=True)
    body = json.loads(messages[1]['content'])
    assert '炽心勇狮' in body['glossary_reference']
    assert not any(x.startswith('完全无关') for x in body['enabled_glossary_evidence']['canonical_terms'])


def test_reference_context_model_proposal_can_pass_without_becoming_confirmed(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot.from_dict(real_fixture()['snapshot'])
    proposed = [{'from': '仪式巨象', 'to': '仪式巨像', 'basis': 'glossary+context'},
                {'from': '赤心勇士', 'to': '炽心勇狮', 'basis': 'glossary+context'}]
    calls = []
    def complete(messages, **kw):
        calls.append(messages)
        return json.dumps({'checked_ids': [3], 'cues': [{'id': 3, 'edits': proposed}]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    row = real_cue()
    result = polishing.call_correction_api([row], [], '', '', '洛克真实片段', '洛克王国：世界',
        [], [], [], glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[3] == '仪式巨像对阵炽心勇狮'
    receipt = row.caption_arbitration['terminology_polish']
    assert receipt['input_text'] == row.text and receipt['validated_text'] == result[3]
    assert receipt['returned_edits'] == proposed
    assert all(x['status'] == 'reference' for x in receipt['sent_candidates']
               if x['canonical'] in ('仪式巨像', '炽心勇狮'))
    assert {'仪式巨像', '炽心勇狮'}.isdisjoint(owner.glossary_snapshot.canonical_terms)
    assert len(calls) == 1


def test_unrelated_confirmed_term_never_authorizes_ordinary_chinese_rewrite():
    from twobyteasr.subtitle_rules.polishing import filter_untrusted_polished_text
    assert filter_untrusted_polished_text('今天感觉无聊', '今天感觉厉害', [], ['洛克王国']) == '今天感觉无聊'


def test_retained_real_deepseek_response_replay_keeps_supported_names_and_ordinary_negatives(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot.from_dict(real_fixture()['snapshot'])
    fixture = json.loads((Path(__file__).parent / 'fixtures/rocom_real_response_1.json').read_text('utf-8-sig'))
    rows = [SpeechSegment(x['id'], x['start'], x['end'], x['primary_text'], x['confidence'], [],
        primary_source=x['primary_source'], moss_text=x['moss_asr'] or '',
        firered_text=x['firered_aed_asr'], qwen_asr_text=x['qwen3_asr'] or '') for x in fixture['cues']]
    def complete(messages, **kw):
        return json.dumps({'checked_ids': [x.segment_id for x in rows],
                           'cues': [x for x in fixture['returned'] if x['edits']]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    result = polishing.call_correction_api(rows, [], '', '', '洛克真实片段', '洛克王国：世界',
        [], [], [], glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[3] == '仪式巨像对阵炽心勇狮'
    assert result[33] == '深蓝鲸'
    assert result[52] == '来到岚鸟'
    assert result[55] == '本来打的就是你仪式巨像'
    assert result[59] == '然后再走到深蓝鲸'
    assert result[60] == '可能是想让岚鸟耗光自己的能量'
    assert result[61] == '让深蓝鲸拿到一个强化回合'
    for row in rows:
        if row.segment_id in (2, 22, 46, 56, 58):
            assert result[row.segment_id] == row.text


def test_ambiguous_homophone_candidates_remain_read_only(context):
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    snapshot = GlossarySnapshot((GlossaryLibrary('fixture', '夹具', 'r1', (),
        ('炽心勇狮', '炽心勇师')),))
    row = real_cue()
    candidates = retrieve_candidates(snapshot, [row])
    assert all(x['ambiguous'] for x in candidates if x['canonical'].startswith('炽心'))
    result, edits = apply_correction_edits(row.text, [row.firered_text, row.qwen_asr_text],
        [{'from': '赤心勇士', 'to': '炽心勇狮', 'basis': 'glossary+context'}],
        contextual_term_candidates=candidates, cue_id=3,
        independent_sources=[('firered', row.firered_text), ('review', row.qwen_asr_text)])
    assert result == row.text and edits == []


def test_context_does_not_count_two_copies_of_one_asr_family_or_rewrite_fragments():
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    snapshot = GlossarySnapshot.from_dict(real_fixture()['snapshot'])
    row = real_cue()
    candidates = retrieve_candidates(snapshot, [row])
    edits = [{'from': '赤心勇士', 'to': '炽心勇狮', 'basis': 'glossary+context'},
             {'from': '阵赤', 'to': '振翅', 'basis': 'glossary+context'}]
    for independent in ([('firered', row.firered_text), ('firered', row.qwen_asr_text)],
                        [('firered', row.firered_text)]):
        result, accepted = apply_correction_edits(row.text, [value for _, value in independent], edits,
            contextual_term_candidates=candidates, cue_id=3, independent_sources=independent)
        assert result == row.text and accepted == []
    ordinary = SpeechSegment(60, 1, 2, '自己的能量', .8, [],
        moss_text='自己的能量', firered_text='自己的能量', qwen_asr_text='自己的能量')
    recalled = retrieve_candidates(snapshot, [ordinary])
    result, accepted = apply_correction_edits(ordinary.text, [ordinary.firered_text, ordinary.qwen_asr_text],
        [{'from': '的能量', 'to': '恶能量', 'basis': 'glossary+context'}],
        contextual_term_candidates=recalled, cue_id=60,
        independent_sources=[('firered', ordinary.firered_text), ('review', ordinary.qwen_asr_text)])
    assert result == ordinary.text and accepted == []


def test_real_final_payload_budget_excludes_lower_ranked_context_without_cutting_cues(context, monkeypatch):
    from dataclasses import replace
    from twobyteasr.subtitle_rules import polishing
    from twobyteasr.providers import provider_input_budget
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot.from_dict(real_fixture()['snapshot'])
    def messages():
        return polishing.call_correction_api([real_cue()], [], '', '', '洛克真实片段',
            '洛克王国：世界', [], [], [], glossary_evidence=owner.glossary_snapshot.evidence(), _messages_only=True)
    first = messages()
    original = json.loads(first[1]['content'])
    # Actual final serialized bytes are the constraint. The last reference
    # must be excluded; editable cue and ASR fields must remain complete.
    measured = provider_input_budget.prepare_input(first, max_tokens=polishing.POLISH_OUTPUT_TOKENS, operation='polish')[1]
    monkeypatch.setitem(provider_input_budget.POLICIES, 'polish',
        replace(provider_input_budget.POLICIES['polish'], payload_bytes=measured['payload_utf8_bytes']-100))
    second = messages()
    body = json.loads(second[1]['content'])
    assert body['terminology_retrieval']['excluded_count'] > 0
    assert body['terminology_retrieval']['excluded_reason'] == 'request_budget'
    assert body['terminology_candidates'][0]['canonical'] == original['terminology_candidates'][0]['canonical']
    assert {key:value for key,value in body['cues'][0].items() if key != 'nearby_glossary_candidates'} == {
        key:value for key,value in original['cues'][0].items() if key != 'nearby_glossary_candidates'}
    provider_input_budget.prepare_input(second, max_tokens=polishing.POLISH_OUTPUT_TOKENS, operation='polish')


def test_complete_production_polish_keeps_context_edit_and_cached_diagnostic(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, cache = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot.from_dict(real_fixture()['snapshot'])
    monkeypatch.setattr(polishing, 'discover_global_domain_term_mappings', lambda *a: [])
    calls = []
    def complete(messages, **kw):
        calls.append(1)
        kw['on_stream_event']('delta', '{')
        return json.dumps({'checked_ids': [3], 'cues': [{'id': 3, 'edits': [
            {'from': '仪式巨象', 'to': '仪式巨像', 'basis': 'glossary+context'},
            {'from': '赤心勇士', 'to': '炽心勇狮', 'basis': 'glossary+context'}]}]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    for _ in range(2):
        result = polishing.polish_subtitles([real_cue()], '洛克真实片段', cache)
        assert result[0].text == '仪式巨像对阵炽心勇狮'
        details = result[0].caption_arbitration['terminology_polish']
        assert details['input_text'] == '仪式巨象对阵赤心勇士'
        assert details['final_text'] == result[0].text and len(details['accepted_edits']) == 2
    assert calls == [1]


def test_snapshot_reference_and_rules_change_polish_cache_key(context, monkeypatch):
    from twobyteasr.recognition.cache import cache_stage_signature
    from twobyteasr.glossary import terminology_retrieval
    from twobyteasr.subtitle_rules import number_fidelity
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('fixture', '夹具', 'r1', (), ('仪式巨像',)),))
    first = cache_stage_signature('polished')
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('fixture', '夹具', 'r2', (), ('仪式巨像', '炽心勇狮')),))
    second = cache_stage_signature('polished')
    assert first != second
    monkeypatch.setattr(terminology_retrieval, 'RULE_VERSION', 'fixture-new-recall-rule')
    third = cache_stage_signature('polished')
    assert third != second
    monkeypatch.setattr(number_fidelity, 'RULE_VERSION', 'fixture-new-numeric-rule')
    assert cache_stage_signature('polished') != third


@pytest.mark.parametrize('enabled', [True, False])
def test_final_polish_retains_small_source_numbers_repetitions_and_saved_switch(context, monkeypatch, enabled):
    from twobyteasr.subtitle_rules import polishing
    core, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('fixture', '夹具', 'r1', (TermEntry('一技能'),)),))
    monkeypatch.setitem(core.RUNTIME_SETTINGS.setdefault('switches', {}), 'prefer_arabic_numbers', enabled)
    monkeypatch.setattr(polishing, 'discover_global_domain_term_mappings', lambda *a: [])
    proposed = [{'from': '一个 一个', 'to': '1个 1个', 'basis': 'model format'},
                {'from': '一技能', 'to': '1技能', 'basis': 'model format'}]
    def complete(messages, **kw):
        assert '普通整数1～9' in messages[0]['content']
        return json.dumps({'checked_ids': [19], 'cues': [{'id': 19, 'edits': proposed}]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    source = '一个 一个 二十个 二十个 一技能'
    row = SpeechSegment(19, 1, 4, source, .85, [], primary_source='moss-host',
        moss_text=source, firered_text=source, qwen_asr_text=source)
    result = polishing.polish_subtitles([row], '数字保真夹具')[0]
    assert result.text == ('一个 一个 20个 20个 一技能' if enabled else source)
    assert result.caption_arbitration['terminology_polish']['returned_edits'] == proposed
    assert result.caption_arbitration['terminology_polish']['rejected_edits']
