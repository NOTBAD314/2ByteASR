"""User regressions: punctuation/repeats, evidence and old layout queues."""
import copy
import pytest
from twobyteasr.glossary.proofread_constraints import constrain_text, policy_of, quoted_evidence
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
from twobyteasr.subtitle_rules.studio_qc import QCResult, QCIssue, QCSeverity, QCCategory, SubtitleQCEngine
from twobyteasr.subtitle_rules.current_issues import current_issue_view


@pytest.mark.parametrize('before,after,expected', [
    ('啊米奥那里加了梨的果酱', '啊，米奥，那里加了梨下的果酱哦', '啊米奥那里加了梨的果酱'),
    ('好难吃好难吃', '好难吃好难吃好难吃', '好难吃好难吃'),
    ('好难吃好难吃', '好难吃', '好难吃好难吃'),
    ('あーギリギリセーフ', 'あギリギリセーフ', 'あーギリギリセーフ'),
    ('古龙，来了', '骨龙，来了。', '骨龙，来了'),
    ('骨笼来了', '骨龙，来了', '骨龙来了'),
    ('C++・Foo-Bar', 'C++・Foo-Baz', 'C++・Foo-Baz'),
    ('teh name', 'the name', 'the name'),
    ('an opn door', 'an open door', 'an open door'),
    ('你好', '“你好”', '你好'),
    ('ありがとう', '「ありがとう」', 'ありがとう'),
])
def test_default_edits_keep_content_and_existing_marks(before, after, expected):
    assert constrain_text(before, after, dict(cleanup=False, punctuation=False)) == expected


def test_independent_switches_and_grounded_omission():
    base = '好难吃好难吃'
    assert constrain_text(base, '好难吃，', dict(cleanup=True, punctuation=False)) == '好难吃'
    assert constrain_text('你好', '你好。', dict(cleanup=False, punctuation=True)) == '你好。'
    sources = {'source_reference': '腐った魚でも入れてるんでしょ'}
    change = dict(reason='原文腐った对应腐烂', evidence_source='source_reference', evidence_quote='腐った')
    assert quoted_evidence(change, sources)
    assert not quoted_evidence(dict(change, evidence_source='audio'), sources)
    assert not quoted_evidence(dict(change, evidence_quote='听到腐烂'), sources)
    assert constrain_text('鱼', '腐烂的鱼', dict(cleanup=False, punctuation=False), evidence=True) == '腐烂的鱼'


@pytest.mark.parametrize('before,after',[('あーーありがとう','あーありがとう'),('ねね、聞いて','ね、聞いて')])
def test_cleanup_on_still_requires_evidence_to_remove_japanese_speech(before,after):
    policy=dict(cleanup=True,punctuation=False)
    assert constrain_text(before,after,policy)==before
    assert constrain_text(before,after,policy,evidence=True)==after


@pytest.mark.parametrize('language,text', [('ja','知るか どうせ腐った魚でも入れてるんでしょ' * 4),
    ('zh','很长的正常口语字幕可以完整保留' * 8), ('en','This is a long sentence with real words. ' * 12)])
def test_long_subtitles_never_create_default_review(language, text):
    p = SubtitleProject(StudioMedia('', duration_ms=20000), cues=[StudioCue('stable',100,700,text)],
        generation_metadata={'language': {'code': language}})
    p.validate()
    p._qc_result = SubtitleQCEngine().analyze(p)
    view = current_issue_view(p)
    assert not any(row.kind in {'line_too_long','unbalanced_lines','high_cps','dense_short_cue'}
                   for row in view.for_cue('stable'))


def test_old_layout_issue_retires_without_acknowledging_real_issue(tmp_path):
    p = SubtitleProject(StudioMedia('', duration_ms=10000), cues=[StudioCue('stable',100,3100,'字幕正文')])
    p.validate()
    original = copy.deepcopy(p.to_dict())
    p._qc_result = QCResult({'stable': (
        QCIssue('line_too_long', QCSeverity.WARNING, QCCategory.READABILITY, 'stable',
                '字幕过长', '按每行14字建议拆条', source='readability_rule'),
        QCIssue('invalid_time', QCSeverity.CRITICAL, QCCategory.TIMELINE, 'stable',
                '具体时间异常', '已定位异常数据', source='timeline_rule'))})
    view = current_issue_view(p)
    assert [r.kind for r in view.for_cue('stable')] == ['invalid_time']
    assert p.studio_state.get('current_issue_decisions') == original['studio_state'].get('current_issue_decisions')
    path = tmp_path/'copy.2byteproj'
    save_project(p,path)
    q = load_project(path)
    q._qc_result = p._qc_result
    assert [r.kind for r in current_issue_view(q).for_cue('stable')] == ['invalid_time']
    assert q.cues[0].text == p.cues[0].text


def test_repeat_pattern_is_diagnostic_but_same_type_with_real_evidence_stays():
    from dataclasses import replace
    from twobyteasr.subtitle_rules.studio_qc import QCEvidence
    from twobyteasr.subtitle_rules.current_issues import invalidate
    p=SubtitleProject(StudioMedia('',duration_ms=5000),cues=[StudioCue('stable',100,2200,'水水水水')])
    p.validate()
    pattern=QCIssue('repeated_character',QCSeverity.WARNING,QCCategory.TEXT,'stable',
                   '连续重复字','仅由文字重复模式触发',source='text_rule')
    p._qc_result=QCResult({'stable':(pattern,)})
    assert not current_issue_view(p).for_cue('stable')
    supported=replace(pattern,evidence=(QCEvidence('FireRed','独立识别稿中的具体冲突','asr'),))
    p._qc_result=QCResult({'stable':(supported,)});invalidate(p)
    assert current_issue_view(p).for_cue('stable')[0].kind=='repeated_character'


def test_real_service_rejects_model_punctuation_and_repeats_but_retains_word_fix(monkeypatch):
    import json
    from types import SimpleNamespace
    from twobyteasr.glossary.terminology import GlossarySnapshot
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    from twobyteasr.studio.subtitle_text_targets import text_entries,review_project
    import twobyteasr.providers.ai_providers as adapter
    bodies=[]
    proposals={'punct':'おはよう。','repeat':'まずいまずいまずい','typo':'骨龙，が来た'}
    def complete(messages,**kwargs):
        body=json.loads(messages[1]['content']);bodies.append((messages,body,kwargs))
        return {'changes':[dict(target_id=t['target_id'],original=t['target_text'],replacement=proposals[t['target_id']],reason='离线候选')
                            for t in body['targets']]}
    monkeypatch.setattr(adapter,'provider_for_stage',lambda *_:SimpleNamespace(complete=complete))
    p=SubtitleProject(StudioMedia('',duration_ms=10000),cues=[StudioCue('punct',0,1000,'おはよう'),
        StudioCue('repeat',1200,2400,'まずいまずい'),StudioCue('typo',2600,3900,'骨笼が来た')],
        generation_metadata={'language':{'code':'ja'}})
    p.validate();entries=text_entries(p,mode='original')
    result=preview_glossary_correction(review_project(p,entries),[e.key for e in entries],GlossarySnapshot(),{},use_ai=True)
    assert len(result.hits)==1 and result.hits[0].cue_id=='typo'
    assert result.hits[0].replacement=='龙'
    assert result.receipt['proposed_changes']==1
    assert bodies[0][1]['edit_policy']['cleanup'] is False and bodies[0][1]['edit_policy']['punctuation'] is False
    assert '没有音频输入' in bodies[0][0][0]['content']
    schema=bodies[0][2]['json_schema']
    assert {'edit_type','evidence_source','evidence_quote'} <= schema['properties']['changes']['items']['properties'].keys()
    assert 'issue_type' in schema['properties']['suspects']['items']['properties']
    assert all(not row['final_diff'] for row in result.receipt['segments'] if row['cue_id']!='typo')
