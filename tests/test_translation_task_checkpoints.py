import json
from types import SimpleNamespace

from twobyteasr.recognition.service import RunOptions,CancellationToken
from twobyteasr.recognition.task_journal import TaskJournal


def test_completed_translation_batch_survives_cancel_and_missing_global_cache(tmp_path,monkeypatch):
    from twobyteasr.subtitle_rules import recognition_translation as rt
    from twobyteasr.subtitle_rules import subtitle_translation as translation
    monkeypatch.setattr(rt,'cache_path',lambda:tmp_path/'global.json')
    monkeypatch.setattr(translation,'RECOMMENDED_BATCH_ITEMS',1)
    journal=TaskJournal('translation',tmp_path/'recognition-tasks').create(['media.wav'],RunOptions(job_id='translation')).acquire()
    token=CancellationToken()
    context=SimpleNamespace(subtitle_output='bilingual',task_language='ja',translation_script='zh-Hans',
        game_name='',cancellation_token=token,task_journal=journal)
    class Provider:
        provider_id='fake';model='fake-model'
        def __init__(self):self.calls=0
        def structured_complete(self,messages,schema=None,**kwargs):
            self.calls+=1;request=json.loads(messages[-1]['content'])
            rows=request.get('items') or request.get('cues') or request.get('lines') or []
            return {'items':[{'id':row['id'],'translation':'这是测试译文'} for row in rows]}
        complete=structured_complete
    provider=Provider()
    cues=[SimpleNamespace(cue_id=i,start=float(i),end=float(i+1),speaker='S00',text=text)
          for i,text in ((1,'怖いわ'),(2,'反省します'))]
    def progress(kind,**fields):
        if kind=='subtitle_translation_progress' and fields['done']==1:token.cancel()
    legacy=SimpleNamespace(record_run_event=progress,add_review_item=lambda *a,**k:None)
    first=rt.translate_runtime_cues(cues,context,legacy,provider=provider)
    assert provider.calls==1 and len(first['translations'])==1
    (tmp_path/'global.json').unlink()
    context.cancellation_token=CancellationToken()
    legacy.record_run_event=lambda *a,**k:None
    second=rt.translate_runtime_cues(cues,context,legacy,provider=provider)
    assert len(second['translations'])==2
    assert provider.calls==2  # Only the missing item calls the provider.
    journal.close()
