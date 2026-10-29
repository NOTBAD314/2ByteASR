"""The faster preview guard retains the same complete document contract."""
import copy,hashlib,json,random
from tests.test_subtitle_translation import make_project
from twobyteasr.studio.studio_find_replace import PreviewBinding, _evidence_digest, _dataclass_json


def old_digest(project):
    payload=PreviewBinding._document_payload(project)
    evidence=payload.pop('asr_evidence',None)
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,default=_dataclass_json).encode('utf8'))
    digest.update(_evidence_digest(project,evidence,trust_rows=False).encode('ascii'))
    return digest.hexdigest()


def test_digest_matches_original_across_nested_metadata_and_view_changes():
    project=make_project()
    project.asr_evidence={'r0':{'words':[{'text':'火','start':1.2,'end':1.5}], 'raw':{'a':[1,None,True,'😀']}}}
    project.studio_state['last_selected_cue']='c1'
    before=copy.deepcopy(project)
    rng=random.Random(29)
    for i in range(30):
        assert PreviewBinding._document_fingerprint(project)==old_digest(project)
        cue=project.cues[rng.randrange(len(project.cues))]
        if i%4==0:cue.text+='字'
        elif i%4==1:cue.transform['position_x']=i*10
        elif i%4==2:project.asr_evidence['r0']['raw']['a'].append(i)
        else:project.studio_state['playhead_ms']=i*100
    assert PreviewBinding._document_fingerprint(before)==old_digest(before)


def test_in_place_style_and_evidence_changes_still_reject_preview():
    project=make_project();binding=PreviewBinding.capture(project)
    project.styles[0].font_size+=1
    assert not binding.matches(project)
    binding=PreviewBinding.capture(project)
    project.asr_evidence['new']={'nested':['must invalidate']}
    assert not binding.matches(project)
