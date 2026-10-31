from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.recognition.processing_recovery import capture_unit,input_matches
from twobyteasr.app.stage_retry import proposal_hits
from tests.test_stage9_cache_and_budget import context


def test_spaced_language_retry_retains_word_boundaries_and_original_cue_offsets():
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue('a',0,1000,'La vettura'),StudioCue('b',1000,2000,'va bene')])
    p.generation_metadata['language']={'code':'it'}
    unit={'capture_by_id':True,'cue_ids':['a','b']}
    captured=capture_unit(p,unit)
    assert captured['text']=='La vettura va bene'
    assert captured['parts'][1]['offset']==len('La vettura ')
    hits,pending=proposal_hits({'input':captured},'La vettura va molto bene')
    assert not pending and len(hits)==1 and hits[0].cue_id=='b' and hits[0].replacement=='va molto bene'
    assert input_matches(p,captured)
    p.cues[1].text='nuovo testo'
    assert not input_matches(p,captured)


def test_chinese_retry_keeps_existing_character_coordinates():
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue('a',0,1000,'第一句'),StudioCue('b',1000,2000,'第二句')])
    p.generation_metadata['language']={'code':'zh'}
    captured=capture_unit(p,{'capture_by_id':True,'cue_ids':['a','b']})
    assert captured['text']=='第一句第二句' and captured['parts'][1]['offset']==3


def test_frame_rounded_neighbor_is_context_while_a_short_owned_cue_survives():
    p=SubtitleProject(media=StudioMedia(''),cues=[
        StudioCue('previous',15467,17233,'frase precedente',evidence_refs=['segment:2']),
        StudioCue('current',17233,20000,'Non è',evidence_refs=['segment:2']),
        StudioCue('short',20000,20020,'il',evidence_refs=['segment:2']),
        StudioCue('last',20020,25860,'mondiale',evidence_refs=['segment:2'])])
    p.generation_metadata['language']={'code':'it'};p.render_settings['fps']=30
    captured=capture_unit(p,{'evidence_refs':['segment:2'],'source_range_ms':[17220,25860]})
    assert [row['cue_id'] for row in captured['parts']]==['current','short','last']
    assert captured['text']=='Non è il mondiale'


def test_retry_auto_protocol_matches_resolved_original_receipt():
    import json
    from twobyteasr.app.completion_retry import _retry_options
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    settings={'models':{'polish_provider':'deepseek','polish_model':'deepseek-flash',
        'polish_transport':'openai_compatible','polish_protocol':'auto',
        'polish_base_url':'https://api.deepseek.com/v1'},'switches':{}}
    snapshot=resolve_provider_snapshot(settings,stage='polish')
    p=SubtitleProject(media=StudioMedia(''))
    report={'events':[{'event':'asr_provider_snapshot','stage':'polished',**snapshot.public_identity()}]}
    configured=_retry_options(p,report,RunOptions(settings_snapshot_json=json.dumps(settings)))
    assert json.loads(configured.settings_snapshot_json)['models']['polish_protocol']==snapshot.protocol


def test_real_retry_uses_project_content_language_and_preserves_latin_punctuation(monkeypatch,context):
    import json
    from types import SimpleNamespace
    from twobyteasr.app.stage_retry import execute_unit
    from twobyteasr.recognition.service import RunOptions,CancellationToken
    from twobyteasr.recognition.run_context import get_runtime_context
    from tests.test_stage9_provider_snapshot import config
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue('a',0,1000,'La vettura va bene.')])
    p.generation_metadata['language']={'code':'it'}
    unit={'stage':'polish','original_ids':[1],'cue_ids':['a'],'capture_by_id':True}
    unit['input']=capture_unit(p,unit)
    seen=[]
    def complete(messages,**kw):
        seen.append(get_runtime_context().task_language)
        return json.dumps({'checked_ids':[1],'cues':[]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    result=execute_unit(p,{},RunOptions(settings_snapshot_json=json.dumps(config())),unit,CancellationToken())
    assert seen==['it'] and result['status']=='completed_no_change'
    assert result['proposed_text']=='La vettura va bene.'
