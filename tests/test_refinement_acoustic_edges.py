import copy
from types import SimpleNamespace as NS
from twobyteasr.recognition import ctc_alignment as ctc,cue_boundary_refine as pause


def cue(start,end,first,last):
    return NS(start=start,end=end,speaker='S1',text='あいう',forced_alignment=dict(segments=[
        dict(char_start=0,char_end=1,start_ms=first[0],end_ms=first[1],start_basis='cue_edge',end_basis='model'),
        dict(char_start=1,char_end=3,start_ms=last[0],end_ms=last[1],start_basis='model',end_basis='cue_edge')]))


def run_ctc(monkeypatch,cues,starts):
    monkeypatch.setattr(ctc,'model_dir',lambda:'fixture-model')
    monkeypatch.setattr(ctc,'run_worker',lambda audio,jobs:dict(results=[]))
    monkeypatch.setattr(ctc,'ctc_starts',lambda jobs,payload:starts)
    return ctc.apply_to_runtime_cues(cues,None,NS(RUNTIME_SETTINGS={},record_run_event=lambda *a,**k:None),fps=30)


def test_ctc_does_not_move_first_start_past_its_measured_end(monkeypatch):
    item=cue(2.,3.,(2000,2010),(2400,3000));before=copy.deepcopy(vars(item))
    assert run_ctc(monkeypatch,[item],{'0':2050})==[]
    assert vars(item)==before


def test_ctc_does_not_trim_previous_tail_before_its_measured_start(monkeypatch):
    left=cue(1.,2.,(1000,1300),(1970,2000));right=cue(2.,3.,(2000,2200),(2600,3000))
    before=copy.deepcopy([vars(left),vars(right)])
    assert run_ctc(monkeypatch,[left,right],{'1':1940})==[]
    assert [vars(left),vars(right)]==before


def test_pause_snap_is_atomic_when_cut_would_invert_edge_piece(monkeypatch):
    left=cue(1.,2.,(1000,1300),(1970,2000));right=cue(2.,3.,(2000,2200),(2600,3000))
    monkeypatch.setattr(pause,'refine_cuts',lambda *a,**kw:[pause.CutChange('0','1',2000,1940,1880,1940,20.)])
    before=copy.deepcopy([vars(left),vars(right)])
    assert pause.apply_to_runtime_cues([left,right],None,NS(record_run_event=lambda *a,**k:None),fps=30)==[]
    assert [vars(left),vars(right)]==before
