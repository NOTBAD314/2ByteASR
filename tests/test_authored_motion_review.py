import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import pytest
from twobyteasr.caption_design.authored_motion_review import capture_motion_review
from twobyteasr.caption_design.authored_keyframe_review import same_provider_reviewer, review_frame_paths


def test_real_contact_sheets_cover_both_boundaries_and_short_hold(monkeypatch,tmp_path):
    import io
    monkeypatch.setattr('twobyteasr.caption_design.web_theme.theme_archive_html',lambda *a,**kw:str(kw['duration_seconds']))
    class Service:
        def __init__(self):self.calls=[]
        def live_set(self,html,**kw):self.duration=float(html)*1000
        def live_pause(self,*,cue_ms,stage_ms):
            assert cue_ms==stage_ms
            self.calls.append((self.duration,cue_ms))
            image=Image.new('RGBA',(1920,1080))
            if 0<cue_ms<self.duration:image.paste('#aa4528',(300,600,1300,880))
            data=io.BytesIO();image.save(data,format='PNG');return data.getvalue()
    service=Service()
    paths,receipt=capture_motion_review(service,{'motionSpec':{'buildMs':800,'resolveMs':500}},'原文',tmp_path)
    assert len(paths)==3 and all(Image.open(p).size==(1920,512) for p in paths)
    for dur in (6000,1500):
        samples=[r for r in receipt['samples'] if r['duration_ms']==dur]
        assert len(samples)==15
        assert samples[0]['milliseconds']==0 and samples[-1]['milliseconds']==dur
        assert samples[0]['subject_bbox'] is None and samples[-1]['subject_bbox'] is None
        assert len([r for r in samples if r['label']=='motion_hold' and r['subject_bbox']])==5
        assert dur-min(d for span,d in service.calls if span==dur and d>dur*.85)<dur*.15
    assert receipt['crop']==[276,576,1324,904] and receipt['same_scale']


def test_reviewer_receives_departure_contact_and_fallback_end(tmp_path):
    proof={'sample_text':'字幕','viewport':[1920,1080],'frames':[]}
    for name in ('entrance','hero','hold','exit','end','detail','game','motion_entry','motion_hold','motion_exit'):
        path=tmp_path/(name+'.png');path.write_bytes(name.encode())
        proof['frames'].append(dict(label=name,path=str(path)))
    requests=[]
    class Client:
        def capabilities(self):return SimpleNamespace(vision=True)
        def complete(self,messages,**kw):requests.append(messages);return 'observed'
    review=same_provider_reviewer(Client(),SimpleNamespace(provider='fixture',model='selected'))
    review(proof)
    import base64
    data=requests[0][0]['content'][1:]
    sent={base64.b64decode(row['image_url']['url'].split(',')[1]).decode() for row in data}
    assert sent=={'motion_entry','motion_hold','motion_exit','detail','game'}
    proof['frames']=[r for r in proof['frames'] if not r['label'].startswith('motion_')]
    assert {'exit.png','end.png'} <= {Path(p).name for p in review_frame_paths(proof)}


def test_surface_scope_allows_text_clipped_ink_but_not_body_visibility():
    from twobyteasr.caption_design.theme_design_preservation import validate_surface_revision
    original={'cueCss':'.copy{position:absolute;color:red}'}
    validate_surface_revision(original,{'cueCss':'.copy{position:absolute;color:red;background:linear-gradient(red,brown);-webkit-background-clip:text;-webkit-text-fill-color:transparent}'})
    with pytest.raises(ValueError):validate_surface_revision(original,{'cueCss':'.copy{position:absolute;color:red;opacity:0}'})
