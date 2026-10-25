import json
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.studio import studio_highlight_analyzer as analyzer


def fixture():
    return SubtitleProject(media=StudioMedia(path='record.flv',duration_ms=100000),cues=[
        StudioCue('before',1000,3000,'先前的内容。'),
        StudioCue('setup',20000,23000,'如果这次再不行就先休息。'),
        StudioCue('core',23500,27000,'没想到真的成功了！'),
        StudioCue('reply',28000,32000,'先不要着急，再仔细看看。'),
        StudioCue('after',50000,52000,'我们继续往前。')])


def test_ai_prompt_refs_and_real_boundaries_survive_whole_pipeline(monkeypatch):
    seen=[]
    class Provider:
        def complete(self,messages,**kwargs):
            seen.append(kwargs)
            payload=json.loads(messages[1]['content']);window=payload['windows'][0]
            assert payload['preferred_length_seconds']==[30,180]
            rows={row['text']:row for row in window['evidence'] if row['kind']=='subtitle'}
            a=rows['如果这次再不行就先休息。'];b=rows['先不要着急，再仔细看看。'];k=rows['没想到真的成功了！']
            return json.dumps({'candidates':[dict(candidate_id=window['candidate_id'],
                title='说好不行就休息，随后说成功了',clip_reason='保留准备放弃、成功反应和后续提醒。',
                evidence_refs=[a['id'],k['id'],b['id']],recommended_range={'start_ref':a['id'],'end_ref':b['id']},
                key_moment_ref=k['id'])]})
    monkeypatch.setattr(analyzer,'provider_for_stage',lambda *a,**kw:Provider())
    result=analyzer.analyze_highlights(fixture(),mode='subtitles',post=lambda:None,runtime_settings={})
    assert result['llm_status']=='completed'
    assert result['candidates'][0].clip_range==(20000,32000)
    assert result['candidates'][0].key_moment_ms==23500
    assert seen[0]['enable_thinking'] is False and seen[0]['json_schema']
    assert not result['candidates'][0].user_confirmed


def test_empty_real_response_downgrades_without_using_raw_context_as_cut(monkeypatch):
    class Empty:
        def complete(self,*a,**kw):return ''
    monkeypatch.setattr(analyzer,'provider_for_stage',lambda *a,**kw:Empty())
    p=fixture();p.cues=p.cues[1:4]  # excerpt, neither surrounding boundary known
    result=analyzer.analyze_highlights(p,mode='subtitles',post=lambda:None,runtime_settings={})
    assert result['llm_status']=='local_fallback'
    assert result['candidates'] and all(c.clip_range is None for c in result['candidates'])
    assert all(c.origin=='local' for c in result['candidates'])
