"""Real outgoing scene/term evidence and scoped normalization contracts."""
import copy
import json
from types import SimpleNamespace

from tests.test_stage9_cache_and_budget import context
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry, TermResolver, apply_to_segments


def library(identity='custom-game', name='自定义比赛', revision='7', terms=()):
    return GlossaryLibrary(identity, name, revision, tuple(terms), profile_json=json.dumps(
        {'_content_domain': {'id': identity, 'name': name, 'source': 'saved_library_game'}}, ensure_ascii=False))


def snapshot():
    return GlossarySnapshot((library(terms=(TermEntry('CHIOCHOO', ('球球',), category='选手 ID'),
        TermEntry('autumn', ('奥特曼',), category='选手 ID'),
        TermEntry('SuMM3R', ('夏老师',), category='选手 ID'),
        TermEntry('闪光弹', category='技能'))),))


def test_scene_priority_unique_domains_and_mixed_without_remote_guess():
    from twobyteasr.recognition.content_scene import resolve_content_scene
    owner = SimpleNamespace(enable_domain_terms=True, game_name='')
    scene = resolve_content_scene(owner, snapshot())
    assert scene.domain == '自定义比赛' and scene.source == 'enabled_glossary_metadata'
    assert dict(scene.glossary_versions) == {'custom-game': '7'}
    owner.game_name = '用户明确场景'
    assert resolve_content_scene(owner, snapshot()).domain == '用户明确场景'
    assert resolve_content_scene(owner, snapshot()).source == 'user_selected'
    owner.game_name = ''
    mixed = resolve_content_scene(owner, GlossarySnapshot((library(), library('other', '另一款'))))
    assert mixed.domain == '' and mixed.source == 'mixed_enabled_glossaries'
    same_game = resolve_content_scene(owner, GlossarySnapshot((library(), library('personal-extra', '自定义比赛'))))
    assert same_game.domain == '自定义比赛' and same_game.source == 'enabled_glossary_metadata'
    assert set(same_game.domain_ids) == {'custom-game', 'personal-extra'}
    generic = GlossarySnapshot((GlossaryLibrary('personal', '常用词', '1'),))
    assert resolve_content_scene(owner, generic).source == 'unknown'


def test_local_aliases_keep_canonical_case_original_pronunciation_and_ordinary_media(context):
    from twobyteasr.recognition.content_scene import resolve_content_scene
    _, owner, _ = context
    owner.enable_domain_terms = True; owner.glossary_snapshot = snapshot()
    resolver = TermResolver(snapshot()); scene = resolve_content_scene(owner)
    for source, target in [('而且球球能奶自己', '而且CHIOCHOO能奶自己'),
                           ('还是在等奥特曼出结果', '还是在等autumn出结果'),
                           ('夏老师架住了这个位置', 'SuMM3R架住了这个位置')]:
        assert resolver.resolve(source, scene=scene).text == target
        assert resolver.resolve(target, scene=scene).text == target
    ordinary = resolver.resolve('小时候喜欢看奥特曼', scene=scene)
    assert ordinary.text == '小时候喜欢看奥特曼'
    assert any(hit.reason == 'alias_context_topic_conflict' for hit in ordinary.skipped)
    assert resolver.resolve('小时候喜欢看奥特曼，球球能奶自己', scene=scene).text == '小时候喜欢看奥特曼，CHIOCHOO能奶自己'
    assert resolver.resolve('小时候喜欢看奥特曼，奥特曼这个选手现在出结果', scene=scene).text == '小时候喜欢看奥特曼，autumn这个选手现在出结果'
    assert resolver.resolve('奥特曼这个选手小时候喜欢看动画', scene=scene).text == 'autumn这个选手小时候喜欢看动画'
    assert resolver.resolve('我喜欢看奥特曼打比赛', scene=scene).text == '我喜欢看autumn打比赛'
    assert resolver.resolve('我喜欢看奥特曼电影里的比赛', scene=scene).text == '我喜欢看奥特曼电影里的比赛'
    row = SpeechSegment(1, 0, 2, '球球奶自己', .9,
        [WordUnit(0, .3, '球', .9), WordUnit(.3, .6, '球', .9), WordUnit(.6, 2, '奶自己', .9)])
    result = apply_to_segments([row], owner.glossary_snapshot)[0]
    assert result.text == 'CHIOCHOO奶自己'
    assert result.words[0].text == 'CHIOCHOO' and result.words[0].start == 0 and result.words[0].end == .6


def test_actual_model_messages_contain_scene_spans_entities_and_prompt_version(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    from twobyteasr.providers.asr_provider_snapshot import POLISH_PROMPT_VERSION
    _, owner, _ = context
    owner.enable_domain_terms = True; owner.glossary_snapshot = snapshot()
    row = SpeechSegment(1, 0, 2, '球球交出了建议', .8, [], primary_source='moss-dialogue',
        moss_text='球球交出了建议', firered_text='球球交出了闪光弹', qwen_asr_text='球球交出了闪光弹')
    sent = []
    def complete(messages, **kwargs):
        body = json.loads(messages[1]['content']); sent.append(body)
        assert body['asr_sources']['F'] == 'FireRed-AED'
        assert body['cues'][0]['asr'] == [[['F', 'Q'], '球球交出了闪光弹']]
        assert 'cue_ids' in body['match_fields'] and 'start' in body['match_fields']
        suspects = [dict(zip(body['suspect_fields'], value)) for value in body['suspects']]
        results = [{'suspect_id': value['suspect_id'], 'disposition': 'review', 'evidence': '需听审'} for value in suspects]
        return json.dumps({'checked_ids': [1], 'cues': [], 'suspect_results': results}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: SimpleNamespace(complete=complete))
    result = polishing.call_correction_api([row], [], '', '', '素材', '', [], [], [],
        glossary_evidence=snapshot().evidence())
    assert result[1] == row.text
    assert sent[0]['content_scene']['domain'] == '自定义比赛'
    assert sent[0]['content_scene']['source'] == 'enabled_glossary_metadata'
    assert sent[0]['prompt_version'] == POLISH_PROMPT_VERSION
    candidates = sent[0]['terminology_candidates'] + [dict(zip(sent[0]['context_term_fields'], value)) for value in sent[0]['context_terms']]
    assert any(candidate['canonical'] == '闪光弹' for candidate in candidates)
    assert any(dict(zip(sent[0]['suspect_fields'], value))['surface'].startswith('建议') for value in sent[0]['suspects'])
    assert row.caption_arbitration['terminology_polish']['quality_state'] == 'pending_suspect_adjudication'


def test_missing_suspect_receipt_is_not_quality_pass(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True; owner.glossary_snapshot = snapshot()
    row = SpeechSegment(8, 0, 1, 'Ghost到了', .8, [], primary_source='moss-dialogue')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: SimpleNamespace(
        complete=lambda *a, **kw: json.dumps({'checked_ids': [8], 'cues': []})))
    result = polishing.call_correction_api([row], [], '', '', '', '', [], [], [], glossary_evidence=snapshot().evidence())
    assert result.succeeded == {8}
    receipt = row.caption_arbitration['terminology_polish']
    assert receipt['unreviewed_suspects'] and receipt['quality_state'] == 'pending_suspect_adjudication'


def test_receipt_for_a_suspect_never_sent_is_dropped_without_a_retry(context, monkeypatch):
    # 2026-10-18 (日常 19 batch 11): with no suspects sent the model invented "s127-1"
    # and the whole batch was retried as if the answer were broken.
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    row = SpeechSegment(127, 0, 1, '普通的一句话', .8, [], primary_source='moss-dialogue')
    calls = []
    def complete(messages, **kwargs):
        calls.append(json.loads(messages[1]['content']))
        return json.dumps({'checked_ids': [127], 'cues': [], 'suspect_results': [
            {'suspect_id': 's127-1', 'disposition': 'keep', 'evidence': '模型自拟'}]}, ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: SimpleNamespace(complete=complete))
    result = polishing.call_correction_api([row], [], '', '', '', '', [], [], [])
    assert len(calls) == 1 and calls[0]['suspects'] == [] and result.succeeded == {127}
    events = [json.loads(line) for line in open(owner.event_log_path, encoding='utf-8')]
    dropped = [e for e in events if e.get('event') == 'terminology_unsolicited_suspect_receipts_dropped']
    assert len(dropped) == 1 and dropped[0]['suspect_ids'] == ['s127-1']


def test_position_candidates_revision_cache_and_explicit_spans(context):
    from twobyteasr.glossary.terminology_retrieval import retrieve_candidates, _catalog_index
    from twobyteasr.subtitle_rules.correction_safety import apply_correction_edits
    from twobyteasr.recognition.content_scene import resolve_content_scene
    _, owner, _ = context
    owner.enable_domain_terms = True; owner.glossary_snapshot = snapshot()
    row = SpeechSegment(9, 0, 1, '球球看见球球', .8, [])
    first = retrieve_candidates(snapshot(), [row], scene=resolve_content_scene(owner))
    hits = next(value for value in first if value['canonical'] == 'CHIOCHOO')['matches']
    assert {(value['start'], value['end']) for value in hits if value['asr_source'] == 'text'} >= {(0, 2), (4, 6)}
    before = _catalog_index.cache_info().hits
    retrieve_candidates(snapshot(), [row]); assert _catalog_index.cache_info().hits > before
    revised = GlossarySnapshot((library(revision='8', terms=(TermEntry('NEW', ('新名字',)),)),))
    assert _catalog_index(revised) != _catalog_index(snapshot())
    result, applied = apply_correction_edits(row.text, [],
        [{'from': '球球', 'to': 'CHIOCHOO', 'start': 0, 'end': 2, 'basis': 'glossary+context'},
         {'from': '球球', 'to': 'CHIOCHOO', 'start': 4, 'end': 6, 'basis': 'glossary+context'}],
        independent_sources=[], contextual_term_candidates=first, cue_id=9)
    assert result == 'CHIOCHOO看见CHIOCHOO' and len(applied) == 2


def test_actual_reference_family_moss_dialogue_uses_firered_and_model_labels_do_not_add_votes(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    row = SpeechSegment(38, 0, 1, 'panda也收掉了stu', .78, [], primary_source='moss-dialogue',
        moss_text='panda也收掉了stu', firered_text='padman也收掉了st', qwen_asr_text='个帕德曼也收掉了stew')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: SimpleNamespace(complete=lambda *a, **kw:
        json.dumps({'checked_ids': [38], 'cues': [{'id': 38, 'edits': [{'from': 'panda', 'to': 'padman', 'basis': 'firered+qwen3'}]}]})))
    result = polishing.call_correction_api([row], [], '', '', '', '', [], [], [])
    assert result[38] == row.text
    rejected = row.caption_arbitration['terminology_polish']['rejected_edits'][0]
    assert rejected['rule_id'] == 'length_change_without_support'
    assert rejected['evidence']['independent_exact_support'] == 1
    assert rejected['evidence']['model_evidence_is_not_support'] is True


def test_local_confirmed_alias_identity_cannot_be_reversed_by_asr_votes(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = GlossarySnapshot((library(terms=(
        TermEntry('CHIOCHOO', ('球球',), category='选手 ID'),
        TermEntry('CHICHOO', category='选手 ID'))),))
    row = SpeechSegment(49, 0, 1, '球球到了一个位置', .78, [], primary_source='moss-dialogue',
        moss_text='球球到了一个位置', firered_text='CHICHOO到了一个位置', qwen_asr_text='CHICHOO到了一个位置')
    apply_to_segments([row], owner.glossary_snapshot)
    assert row.text == 'CHIOCHOO到了一个位置'
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: SimpleNamespace(complete=lambda *a, **kw:
        json.dumps({'checked_ids': [49], 'cues': [{'id': 49, 'edits': [
            {'from': 'CHIOCHOO', 'to': 'CHICHOO', 'start': 0, 'end': 8, 'basis': 'glossary+firered+qwen3+context'}]}]})))
    result = polishing.call_correction_api([row], [], '', '', '', '', [], [], [], glossary_evidence=owner.glossary_snapshot.evidence())
    assert result[49] == 'CHIOCHOO到了一个位置'
    assert result.succeeded == {49}
    assert row.caption_arbitration['terminology_polish']['rejected_edits'][0]['rule_id'] == 'existing_latin_changed'
    # A model's "replace" receipt with no real accepted patch must not turn
    # an untouched suspect into a completed quality check.
    suspect_row = SpeechSegment(50, 0, 1, '交出了建议', .78, [], primary_source='moss-dialogue')
    def contradictory_receipt(messages, **_kwargs):
        body = json.loads(messages[1]['content'])
        suspects = [dict(zip(body['suspect_fields'], value)) for value in body['suspects']]
        assert suspects
        return json.dumps({'checked_ids': [50], 'cues': [], 'suspect_results': [
            {'suspect_id': value['suspect_id'], 'disposition': 'replace',
             'candidate_id': 'invented-candidate', 'evidence': ''} for value in suspects]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw:
        SimpleNamespace(complete=contradictory_receipt))
    polishing.call_correction_api([suspect_row], [], '', '', '', '', [], [], [], glossary_evidence=owner.glossary_snapshot.evidence())
    receipt = suspect_row.caption_arbitration['terminology_polish']
    assert receipt['quality_state'] == 'pending_suspect_adjudication'
    assert receipt['suspect_results'][0]['validation_state'] == 'invalid'
    assert set(receipt['suspect_results'][0]['validation_errors']) == {
        'empty_evidence', 'unknown_or_unscoped_candidate_id', 'replace_without_accepted_position_edit'}
