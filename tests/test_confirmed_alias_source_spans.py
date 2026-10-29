"""Literal user aliases retain pronunciation spans and honest recall receipts."""
from copy import deepcopy
from types import SimpleNamespace

from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.glossary.terminology import (GlossaryLibrary, GlossarySnapshot, TermEntry,
    TermResolver, apply_to_segments, snapshot_from_pairs)
from twobyteasr.glossary.terminology_retrieval import retrieve_candidates
from twobyteasr.glossary.terminology_support import recall_gaps
from tests.test_stage9_cache_and_budget import context


def test_chinese_nickname_is_one_token_at_the_original_pronunciation_span():
    source = '球球到了一个点'
    segment = SpeechSegment(1, .1, 2.5, source, .82,
        [WordUnit(.1, .3, '球', .8), WordUnit(.3, .5, '球', .85),
         WordUnit(.5, 1.0, '到了', .9), WordUnit(1., 2., '一个', .7),
         WordUnit(2., 2.5, '点', .9)], speaker='S02', final_timing_owner='FireRed')
    snapshot = snapshot_from_pairs([('球球', 'CHIOCHOO')])
    apply_to_segments([segment], snapshot)
    assert segment.text == segment.final_text == 'CHIOCHOO到了一个点'
    assert [(w.text, w.start, w.end) for w in segment.words] == [
        ('CHIOCHOO', .1, .5), ('到了', .5, 1.), ('一个', 1., 2.), ('点', 2., 2.5)]
    assert (segment.start, segment.end, segment.speaker) == (.1, 2.5, 'S02')
    receipt = segment.caption_arbitration['terminology_normalization'][-1]
    assert receipt['alignment_provenance'] == 'derived_term_source_span'
    assert receipt['requires_acoustic_alignment'] is False
    assert receipt['span_mappings'][0]['acoustic_verified_spelling'] is False
    assert receipt['span_mappings'][0]['source_words'] == [
        {'text': '球', 'start': .1, 'end': .3}, {'text': '球', 'start': .3, 'end': .5}]


def test_repeated_nicknames_digits_natural_quantity_and_saved_case_are_preserved():
    source = '小猫小猫一个 11 11 Sop berlin 折'
    words = [WordUnit(i, i + 1, text, .8) for i, text in enumerate(
        ('小猫', '小猫', '一个', '11', '11', 'Sop', 'berlin', '折'))]
    segment = SpeechSegment(1, 0., 8., source, .8, words, speaker='S03')
    snapshot = snapshot_from_pairs([('小猫', 'MyCAT'), ('Sop', 'S0pp'), ('berlin', 'BerLIN'), ('折', 'Zhe')])
    apply_to_segments([segment], snapshot)
    assert segment.text == 'MyCATMyCAT一个 11 11 S0pp BerLIN Zhe'
    assert [w.text for w in segment.words] == ['MyCAT', 'MyCAT', '一个', '11', '11', 'S0pp', 'BerLIN', 'Zhe']
    assert [(w.start, w.end) for w in segment.words] == [(float(i), float(i+1)) for i in range(8)]
    assert segment.end == 8. and segment.speaker == 'S03'


def test_partial_source_token_remains_coarse_and_no_words_does_not_invent_alignment():
    for words in ([], [WordUnit(0., 3., '还是等奥特曼出结果', .8)]):
        segment = SpeechSegment(1, 0., 3., '还是等奥特曼出结果', .8, deepcopy(words))
        apply_to_segments([segment], snapshot_from_pairs([('奥特曼', 'autumn')]))
        assert segment.text == '还是等autumn出结果'
        receipt = segment.caption_arbitration['terminology_normalization'][-1]
        assert receipt['requires_acoustic_alignment'] is True
        assert receipt['alignment_provenance'] == 'term_local_mapping'
        assert segment.start == 0. and segment.end == 3.


def test_scanned_matched_and_replaced_counts_are_distinct_even_when_nothing_changes():
    events = []
    legacy = SimpleNamespace(record_run_event=lambda name, **data: events.append((name, data)))
    snapshot = snapshot_from_pairs([('猫猫', 'CatID')])
    rows = [SpeechSegment(1, 0., 1., '普通句', .8, []), SpeechSegment(2, 1., 2., 'CatID', .8, [])]
    apply_to_segments(rows, snapshot, legacy)
    event = events[0][1]
    assert event['scanned_segment_count'] == 2
    assert event['matched_segment_count'] == 1
    assert event['changed_segment_count'] == event['replacement_count'] == 0
    assert event['segment_count_kind'] == 'changed_segments_legacy'


def test_existing_final_body_case_syncs_word_text_without_claiming_alias_replacement():
    events=[]
    legacy=SimpleNamespace(record_run_event=lambda name,**data:events.append(data))
    segment=SpeechSegment(1,0.,1.,'EDG有预警',.8,
        [WordUnit(0.,.4,'edg',.8),WordUnit(.4,1.,'有预警',.8)])
    apply_to_segments([segment],GlossarySnapshot(),legacy)
    assert segment.text==segment.final_text==''.join(word.text for word in segment.words)=='EDG有预警'
    assert [(word.start,word.end) for word in segment.words]==[(0.,.4),(.4,1.)]
    assert events[0]['word_case_sync_count']==1 and events[0]['replacement_count']==0


def test_missing_alias_is_not_guessed_from_an_enabled_canonical_or_recall_count():
    snapshot = GlossarySnapshot((GlossaryLibrary('v', '瓦罗兰特', '51',
        terms=(TermEntry('CHICHOO', ('CHICHOO',), category='选手 ID'),)),))
    rows = [SpeechSegment(1, 0., 1., '球球被挡住', .8, []),
            SpeechSegment(2, 1., 2., '还在等奥特曼出结果', .8, [])]
    candidates = retrieve_candidates(snapshot, rows)
    gaps = recall_gaps(rows, candidates, snapshot)
    assert {row['surface'] for row in gaps} >= {'球球', '奥特曼'}
    assert all(row['in_snapshot'] is False and row['canonical_inferred'] is False for row in gaps)
    apply_to_segments(rows, snapshot)
    assert [row.text for row in rows] == ['球球被挡住', '还在等奥特曼出结果']


def test_exact_alias_is_recalled_with_original_variant_and_frozen_library_identity():
    snapshot = GlossarySnapshot((GlossaryLibrary('local-v', '测试内容', '7',
        terms=(TermEntry('autumn', ('奥特曼',), category='选手 ID'),)),))
    rows = [SpeechSegment(1, 0., 1., '奥特曼这个位置', .8, [])]
    result = retrieve_candidates(snapshot, rows)
    exact = next(match for row in result if row['canonical'] == 'autumn'
                 for match in row['matches'] if match['method'] == 'exact')
    assert exact['matched_variant'] == '奥特曼' and exact['matched_alias'] is True
    assert result[0]['sources'][0]['library_id'] == 'local-v'
    assert recall_gaps(rows, result, snapshot) == []
    assert TermResolver(GlossarySnapshot()).resolve(rows[0].text).text == rows[0].text


def test_derived_source_spans_survive_project_save_reopen_and_srt_export(tmp_path):
    from twobyteasr.recognition.transcript_data import SubtitleCue
    from twobyteasr.projects.studio_project import create_studio_outputs, load_project
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.subtitle_rules.output import render_srt
    segment = SpeechSegment(1, 0., 2., '小猫准备进攻', .8,
        [WordUnit(0., .4, '小猫', .8), WordUnit(.4, 2., '准备进攻', .9)],
        speaker='S01', final_timing_owner='FireRed')
    apply_to_segments([segment], snapshot_from_pairs([('小猫', 'MyCAT')]))
    cues = [SubtitleCue(1, 0., 2., segment.text, speaker='S01')]
    saved = create_studio_outputs(tmp_path / 'synthetic.mp4', cues, txt_path='', segments=[segment],
        target_project_path=tmp_path / 'source-span.2byteproj')
    project = load_project(saved['project'])
    words, reason = cue_words(project, project.cues[0])
    assert reason == 'derived_term_source_span'
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [('mycat', 0, 400), ('准备进攻', 400, 2000)]
    assert 'MyCAT准备进攻' in render_srt(cues)
    assert project.cues[0].text == segment.final_text


def test_wire_projection_keeps_all_heard_forms_cue_ids_independent_asr_text_and_full_audit():
    import subtitle_core  # initialize the production facade before stage module
    from twobyteasr.subtitle_rules.polishing import _wire_correction_body
    body={'cues':[{'id':1,'primary_text':'小猫来了','moss_asr':'小猫来了','firered_aed_asr':'小苗来了'},
                  {'id':2,'primary_text':'小猫走了','qwen3_asr':'小猫走了'}],
          'terminology_candidates':[{'canonical':'MyCAT','aliases':['小猫'],'status':'confirmed',
             'sources':[{'library_id':'v','library_name':'长名字','origin':'重复元数据','provenance':'user_confirmed','category':'选手 ID','status':'confirmed'}],
             'matches':[{'cue_id':1,'asr_source':'text','heard':'小猫','score':1.,'method':'exact'},
                        {'cue_id':2,'asr_source':'text','heard':'小猫','score':1.,'method':'exact'},
                        {'cue_id':1,'asr_source':'firered_text','heard':'小苗','score':.9,'method':'phonetic'}]}]}
    before=deepcopy(body)
    wire=_wire_correction_body(body)
    assert body==before and wire['cues']==before['cues']
    assert wire['terminology_candidates'][0]['matches'][0]['cue_ids']==[1,2]
    reconstructed=[{key:value for key,value in match.items() if key!='cue_ids'}|{'cue_id':cue_id}
        for match in wire['terminology_candidates'][0]['matches'] for cue_id in match['cue_ids']]
    assert reconstructed==before['terminology_candidates'][0]['matches']


def test_wire_defaults_preserve_primary_family_and_remove_derived_scalar_scores_only():
    import subtitle_core
    from twobyteasr.subtitle_rules.polishing import _wire_correction_body
    body={'cues':[{'id':1,'primary_text':'原文','primary_source':'moss-host','speaker':'S01',
                   'start':1.,'end':2.,'confidence':.78,'reference_consensus':.9,'firered_aed_asr':'参考稿'},
                  {'id':2,'primary_text':'第二句','primary_source':'moss-host','speaker':'S02',
                   'start':2.,'end':3.,'confidence':0.,'reference_consensus':0.,'qwen3_asr':'第二句参考'}]}
    wire=_wire_correction_body(body)
    assert wire['cue_defaults']=={'primary_source':'moss-host'}
    for expected,row in zip(body['cues'],wire['cues']):
        restored={**wire['cue_defaults'],**row}
        assert restored=={key:value for key,value in expected.items() if key not in ('confidence','reference_consensus')}


def test_final_polish_cannot_revert_saved_alias_or_discard_its_original_span(context, monkeypatch):
    """A later checked text artifact can still repeat a source nickname."""
    import subtitle_core
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.glossary_snapshot = snapshot_from_pairs([('小猫', 'MyCAT'), ('sop', 'S0pp')])
    owner.enable_term_search = False
    source = '小猫一个 11 11 sop'
    segment = SpeechSegment(1, 0., 5., source, .8,
        [WordUnit(float(i), float(i+1), text, .8)
         for i, text in enumerate(('小猫', '一个', '11', '11', 'sop'))],
        speaker='S02', final_timing_owner='FireRed', firered_text=source, qwen_asr_text=source)
    # Replay a pre-existing checked text output at the post-provider boundary;
    # this specifically tests final normalization, independent of the API gate.
    def checked_output(*args, **kwargs):
        result = polishing.PolishBatchResult({1: source}, succeeded={1})
        result.details = {1: {'validated_text': source, 'accepted_edits': [], 'rejected_edits': []}}
        return result
    monkeypatch.setattr(polishing, 'call_correction_api', checked_output)
    row = polishing.polish_subtitles([segment], '隔离别名回归')[0]
    assert row.text == row.final_text == 'MyCAT一个 11 11 S0pp'
    assert [word.text for word in row.words] == ['MyCAT', '一个', '11', '11', 'S0pp']
    assert [(word.start, word.end) for word in row.words] == [(float(i), float(i+1)) for i in range(5)]
    assert not any(item.get('requires_acoustic_alignment') for item in
                   row.caption_arbitration['terminology_normalization'])
    assert (row.start, row.end, row.speaker) == (0., 5., 'S02')


def test_checked_no_edit_response_still_reports_missing_name_recall_for_review(context, monkeypatch):
    import json
    from twobyteasr.subtitle_rules import polishing
    _, owner, _ = context
    owner.enable_domain_terms = True
    owner.enable_term_search = False
    owner.glossary_snapshot = GlossarySnapshot((GlossaryLibrary('v', '测试领域', '51',
        terms=(TermEntry('CHICHOO', ('CHICHOO',), category='选手 ID'),)),))
    source = '还在等奥特曼出结果'
    def complete(*args, **kwargs):
        return json.dumps({'checked_ids': [1], 'cues': []})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *args, **kwargs: SimpleNamespace(complete=complete))
    row = polishing.polish_subtitles([SpeechSegment(1, 0., 2., source, .8, [])], '隔离召回审计')[0]
    receipt = row.caption_arbitration['terminology_polish']
    assert row.text == source
    assert receipt['quality_state'] == 'term_review_needed'
    gap = next(item for item in receipt['candidate_usage']['unresolved_recall_gaps']
               if item['surface'] == '奥特曼')
    assert not gap['in_snapshot'] and not gap['canonical_inferred']
    assert any(item['category'] == '术语召回缺口' for item in owner.review_items)
    assert owner.polishing_summary['term_context']['scanned_segments'] == 1
    assert owner.polishing_summary['term_context']['unresolved_recall_gaps'] >= 1
    assert owner.polishing_summary['term_context']['recall_gap_cues'] == 1
