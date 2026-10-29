from types import SimpleNamespace
from twobyteasr.recognition import cue_evidence_slice as module
from twobyteasr.recognition.caption_arbitration import align


def row(text='原始证据投影必须保持正确'):
    return dict(start_ms=0,end_ms=len(text)*100,text=text,
        words=[dict(text=c,start_ms=i*100,end_ms=(i+1)*100) for i,c in enumerate(text)])


def test_many_cue_slices_share_text_map_without_sharing_time_selection(monkeypatch):
    module._text_alignment.cache_clear()
    data=row();data['hyp']='原始证据投影必需保持正确'
    calls=[];original=module.align
    def counted(a,b):calls.append((a,b));return original(a,b)
    monkeypatch.setattr(module,'align',counted)
    for i in range(0,12,2):
        cue=SimpleNamespace(start_ms=i*100,end_ms=(i+2)*100)
        assert module.slice_evidence(data,cue,'hyp') == data['hyp'][i:i+2]
    assert len(calls)==1
    assert module._text_alignment.cache_info().hits>=5


def test_changed_text_and_word_time_invalidate_only_what_changes():
    module._text_alignment.cache_clear();data=row('甲乙丙丁')
    cue=SimpleNamespace(start_ms=0,end_ms=200)
    assert module.slice_evidence(data,cue,'text')=='甲乙'
    data['words'][1]['start_ms']=300;data['words'][1]['end_ms']=400
    assert module.slice_evidence(data,cue,'text')=='甲'
    data['text']='戊乙丙丁'
    assert module.slice_evidence(data,cue,'text')=='戊'
    data['words'][0]['text']='戊'
    assert module.slice_evidence(data,cue,'text')=='戊'


def test_alignment_cache_matches_original_tie_rules_and_is_bounded():
    module._text_alignment.cache_clear()
    for a,b in [('','甲'),('甲',''),('甲乙甲','甲甲乙'),('abc','abc'),('甲乙','乙甲')]:
        assert module._text_alignment(a,b)==tuple(align(a,b))
    for i in range(100):module._text_alignment(str(i),'ref')
    assert module._text_alignment.cache_info().currsize==64
