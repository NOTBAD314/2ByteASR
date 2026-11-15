"""A is delivered before B starts; failures and finalization preserve edits."""
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from tests.test_recognition_result_identity import owned_library,media,CommitPipeline
from tests.test_service_layer import FakeLegacy
from twobyteasr.recognition.service import run_media_queue,RunOptions,MediaResult,_publish_media_delivery
from twobyteasr.projects.studio_project import load_project,save_project
from twobyteasr.recognition.recognition_result import working_reference,verify_result_reference

def test_a_delivered_before_b_failure_and_c_keep_manual_edits(tmp_path,owned_library):
    paths=[media(tmp_path,x+'/same.wav',i) for i,x in enumerate('ABC')]
    delivered=[];events=[];saved=[]
    class Pipeline(CommitPipeline):
        def process_media(self,path,index,total,legacy,runtime_context=None):
            if index==2:
                assert len(delivered)==1
                raise RuntimeError('B fixture failed')
            if index==3:
                assert len(delivered)==1 and Path(delivered[0]['project_path']).read_bytes()==saved[0]
            return super().process_media(path,index,total,legacy,runtime_context=runtime_context)
    def receive(event):
        events.append(event)
        if event.kind=='media_delivered':
            item=event.payload['result'];delivered.append(item)
            if len(delivered)==1:
                p=load_project(item['project_path']);p.cues[0].text='人工校对后的文字'
                p.cues[0].start_ms+=20;p.cues[0].end_ms-=20
                # Remove the delivered cue and add a new stable ID: old indices
                # and old full-project snapshots must never be replayed.
                from dataclasses import replace
                p.cues=[replace(p.cues[0],id='manual-split',text='人工切割保留')]
                save_project(p,item['project_path']);saved.append(Path(item['project_path']).read_bytes())
    result=run_media_queue(paths,RunOptions(job_id='early-delivery'),receive,
        _legacy=FakeLegacy(tmp_path),_pipeline=Pipeline(),_skip_environment_preflight=True)
    assert [i.status for i in result.results]==['success','failed','success']
    assert len(delivered)==2 and Path(delivered[0]['project_path']).read_bytes()==saved[0]
    p=verify_result_reference(working_reference(delivered[0]['result_ref_json']))
    assert p.cues[0].id=='manual-split' and p.cues[0].text=='人工切割保留'
    kinds=[e.kind for e in events]
    assert kinds.index('media_delivered')<kinds.index('media_failed')<kinds.index('run_completed')

def test_publish_rejects_empty_unsaved_and_failed(tmp_path):
    class Legacy:
        def record_run_event(self,*a,**k):raise AssertionError('must not publish')
    assert not _publish_media_delivery(Legacy(),MediaResult('a','success'))
    assert not _publish_media_delivery(Legacy(),MediaResult('b','failed',project_path='fake'))

def test_background_reference_retains_identity_after_edit():
    from twobyteasr.app.background_recognition import BackgroundRecognitionMixin
    ref=json.dumps({'job_id':'a','result_revision':'r'})
    host=SimpleNamespace(_delivered_project_refs={str(Path('a.2byteproj').resolve()):ref})
    item=MediaResult('a','success',project_path='a.2byteproj',result_ref_json=ref)
    assert json.loads(BackgroundRecognitionMixin._background_reference(host,item))['scope']=='working'
    other=MediaResult('a','success',project_path='a.2byteproj',result_ref_json='different')
    assert BackgroundRecognitionMixin._background_reference(host,other)=='different'


def test_cancel_remaining_preserves_delivered_a(tmp_path,owned_library):
    from twobyteasr.recognition.service import CancellationToken
    token=CancellationToken();delivered=[]
    def event(e):
        if e.kind=='media_delivered':delivered.append(e.payload['result'])
    class Pipeline(CommitPipeline):
        def process_media(self,path,index,total,legacy,runtime_context=None):
            if index==2:
                token.cancel();token.raise_if_cancelled()
            return super().process_media(path,index,total,legacy,runtime_context=runtime_context)
    result=run_media_queue([media(tmp_path,x+'.wav') for x in 'ABC'],RunOptions(job_id='cancel-remaining'),event,
        cancel_token=token,_legacy=FakeLegacy(tmp_path),_pipeline=Pipeline(),_skip_environment_preflight=True)
    assert [row.status for row in result.results]==['success','cancelled','cancelled']
    assert len(delivered)==1 and verify_result_reference(delivered[0]['result_ref_json'])
