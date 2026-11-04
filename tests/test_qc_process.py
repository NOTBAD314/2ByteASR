import io
import os
import subprocess
import sys
from pathlib import Path
import pytest
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine,TerminologyEntry
from twobyteasr.subtitle_rules.qc_process import evaluate,read_packet,write_packet

def fixture():
    p=SubtitleProject(media=StudioMedia(path='',duration_ms=6000))
    p.cues=[StudioCue('a',0,150,'错误词'),StudioCue('b',120,2500,'这是一句正常的字幕。'),StudioCue('c',2500,5900,'重复重复重复')]
    p.validate()
    return p

def canonical(result):
    return {k:[x.to_dict() for x in v] for k,v in result.issues_by_cue.items()}

def test_snapshot_process_rules_match_same_canonical_project():
    p=fixture();engine=SubtitleQCEngine();terms=(TerminologyEntry('正确词',('错误词',)),)
    snapshot=StudioRevisionStore(p).persistence
    expected=canonical(engine.analyze(p,terminology=terms))
    # An edit after capture must not enter this job.
    p.cues[0].text='已修改'
    assert canonical(evaluate(snapshot,engine.config,terms)['result'])==expected

def test_packet_protocol_rejects_truncation_and_unbounded_input():
    with pytest.raises(EOFError):read_packet(io.BytesIO(b'\x03'))
    with pytest.raises(ValueError):read_packet(io.BytesIO(b'\xff\xff\xff\xff'))
    stream=io.BytesIO();write_packet(stream,{'data':[1,2]});stream.seek(0)
    assert read_packet(stream)=={'data':[1,2]}

def test_real_worker_reuses_process_for_multiple_requests(tmp_path):
    root=Path(__file__).resolve().parents[1]
    env=os.environ.copy();env['TWOBYTEASR_TEST_ROOT']=str(tmp_path);env['PYTHONUTF8']='1'
    child=subprocess.Popen([sys.executable,'-B',str(root/'quick_start.py'),'--studio-qc-worker'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        for i in range(2):
            p=fixture();p.cues[0].text+='字'*i
            engine=SubtitleQCEngine()
            write_packet(child.stdin,(StudioRevisionStore(p).persistence,engine.config,()))
            reply=read_packet(child.stdout)
            assert 'error' not in reply,reply
            assert canonical(reply['result'])==canonical(engine.analyze(p))
        child.stdin.close();assert child.wait(10)==0
    finally:
        if child.poll() is None:child.kill();child.wait(10)

def test_late_qc_result_cannot_cross_project_session_or_edit():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_review_ui import StudioReviewMixin
    from twobyteasr.projects.studio_runtime_state import state_for
    p=fixture();runtime=state_for(p);applied=[];restarted=[]
    page=SimpleNamespace(project=p,session=SimpleNamespace(generation=2),_qc_scan_token=7,
        _qc_worker_snapshot_ms=0,_finish_chunked_qc_scan=lambda *x:applied.append(x),
        _start_chunked_qc_scan=lambda:restarted.append(True))
    page._background_qc_current=lambda token:StudioReviewMixin._background_qc_current(page,token)
    for token in [(0,2,0,7),(id(p),1,0,7),(id(p),2,0,6)]:
        StudioReviewMixin._background_qc_ready(page,token,'result',{})
    assert not applied and not restarted
    StudioReviewMixin._background_qc_ready(page,(id(p),2,-1,7),'result',{})
    assert restarted and not applied
    StudioReviewMixin._background_qc_ready(page,(id(p),2,runtime.playback_revision,7),'result',{})
    assert applied==[(p,'result')]
