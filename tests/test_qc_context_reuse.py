"""Reuse the acoustic index at the typed GUI boundary, not for arbitrary callers."""
import pickle
from types import SimpleNamespace
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine,QCResult,_EvidenceTimeIndex
from twobyteasr.studio.studio_review_ui import StudioReviewMixin

def project():
    p=SubtitleProject(StudioMedia('',duration_ms=5000),cues=[StudioCue(str(i),i*1000,i*1000+800,'字幕'+str(i)) for i in range(5)])
    p.validate();p.asr_evidence={'row':{'start_ms':0,'end_ms':900,'text':'UNIQUE_EVIDENCE_BODY'}}
    return p

def test_compact_index_transfers_no_evidence_body_and_binds_current_rows():
    p=project();index=_EvidenceTimeIndex(p.asr_evidence);compact=index.compact()
    assert b'UNIQUE_EVIDENCE_BODY' not in pickle.dumps(compact)
    current={'row':{**p.asr_evidence['row'],'text':'current'}}
    rebound=_EvidenceTimeIndex.bind_compact(current,pickle.loads(pickle.dumps(compact)))
    assert rebound.overlapping(0,800,0)[0][2] is current['row']
    assert [(a,b) for a,b,_ in rebound.overlapping(0,800,0)]==[(a,b) for a,b,_ in index.overlapping(0,800,0)]

def test_incremental_many_builds_one_context_and_default_reads_fresh_data(monkeypatch):
    p=project();engine=SubtitleQCEngine(rules=());previous=engine.analyze(p)
    calls=[];original=_EvidenceTimeIndex.__init__
    def build(self,evidence):calls.append(1);original(self,evidence)
    monkeypatch.setattr(_EvidenceTimeIndex,'__init__',build)
    engine.analyze_incremental_many(p,{'2'},previous)
    assert len(calls)==1
    p.asr_evidence['row']['start_ms']=3000;p.asr_evidence['row']['end_ms']=3900
    engine.analyze_incremental_many(p,{'2'},previous)
    assert len(calls)==2

def test_gui_reuses_bound_index_and_invalidates_after_mapping_change(monkeypatch):
    p=project();store=StudioRevisionStore(p);engine=SubtitleQCEngine(rules=());p._qc_result=engine.analyze(p)
    p._qc_evidence_index_cache=(p.asr_evidence,(store.mapping_revision,len(p.asr_evidence)),_EvidenceTimeIndex(p.asr_evidence))
    page=SimpleNamespace(project=p,_revision_store=store,_qc_engine=engine,_cue_lookup={c.id:c for c in p.cues},
                         _qc_terminology=(),_pending_qc_cue_ids={'2'},selected_cue_id='',_qc_full_scan_pending=False)
    calls=[];original=_EvidenceTimeIndex.__init__
    def build(self,evidence):calls.append(1);original(self,evidence)
    monkeypatch.setattr(_EvidenceTimeIndex,'__init__',build)
    p.cues[2].text='改后的正文'
    StudioReviewMixin._refresh_review_risks(page,{'2'})
    assert not calls
    p.asr_evidence['row']={**p.asr_evidence['row'],'start_ms':3000,'end_ms':3900}
    store.mapping_revision+=1
    StudioReviewMixin._refresh_review_risks(page,{'2'})
    assert len(calls)==1
