from copy import deepcopy
import pytest
from twobyteasr.rendering.caption_asset_identity import asset_dependencies,asset_windows

def props():
    def cue(i,a,b):
        return dict(id=i,text='原文'+i,translation='译文',speaker='A',styleId='s',startMs=a,endMs=b,
            cueDurationMs=b-a,snapshotHash='metadata',visual=dict(name='名字',typography=dict(fontFamily='Test Font'),
                motion=dict(mode='fade',duration=250),fill=dict(color='red')))
    return dict(width=1920,height=1080,fps=60,durationInFrames=600,
        cues=[cue('a',1000,2000),cue('b',5000,6000)],recipes={'unused':{}},
        fontFaces=[dict(family='Test Font',weight=400,style='normal',source='bytes1',sha256='claimed')])

def test_local_edit_only_invalidates_the_asset_whose_frames_use_it():
    p=props();before=asset_dependencies(p,60,119)
    p['cues'][1]['text']='修改其他字幕';p['cues'][1]['visual']['fill']['color']='blue'
    p['recipes']['unused']={'new':'irrelevant'}
    assert before==asset_dependencies(p,60,119)
    p['cues'][0]['text']='修改本条'
    assert before!=asset_dependencies(p,60,119)

@pytest.mark.parametrize('field,value',[('translation','新译文'),('speaker','B'),('localOffsetMs',150),('cueDurationMs',3000)])
def test_rendered_text_speaker_and_authored_clock_are_dependencies(field,value):
    p=props();before=asset_dependencies(p,60,119);p['cues'][0][field]=value
    assert before!=asset_dependencies(p,60,119)

def test_job_ids_and_snapshot_metadata_do_not_invalidate_pixels():
    p=props();before=asset_dependencies(p,60,119)
    p['cues'][0].update(id='another-task',snapshotHash='another-revision',resolvedStyleHash='metadata-only')
    p['cues'][0]['visual']['name']='改名'
    assert before==asset_dependencies(p,60,119)

def test_actual_embedded_font_bytes_invalidate_even_if_declared_digest_is_stale():
    p=props();before=asset_dependencies(p,60,119);p['fontFaces'][0]['source']='bytes2'
    assert before!=asset_dependencies(p,60,119)
    p['fontFaces'].append(dict(family='Unused Font',source='other bytes'))
    same=asset_dependencies(p,60,119);p['fontFaces'][-1]['source']='changed unused bytes'
    assert same==asset_dependencies(p,60,119)

def test_overlap_group_and_global_ambient_dependencies_are_preserved():
    p=props();p['cues'][1].update(startMs=1500,endMs=3000)
    assert asset_windows(p,600)==[(60,179)]
    before=asset_dependencies(p,60,179);p['cues'][1]['text']='重叠字幕修改'
    assert before!=asset_dependencies(p,60,179)
    p=props();p['cues'][0]['visual']['webTheme']={'ambient':'stage'}
    assert asset_windows(p,600)==[(0,599)]
    before=deepcopy(asset_dependencies(p,60,119));p['cues'][1]['text']='全局依赖修改'
    assert before!=asset_dependencies(p,60,119)

def test_fractional_frames_and_still_relocation_keep_correct_scope():
    p=props();p['fps']=60000/1001
    assert asset_windows(p,600)==[(60,119),(300,359)]
    first=asset_dependencies(p,60,60,still=True)
    p['cues'][0].update(startMs=2000,endMs=4000,cueDurationMs=2000)
    assert first==asset_dependencies(p,120,120,still=True)
    p['width']=3840
    assert first!=asset_dependencies(p,120,120,still=True)

def test_qt_still_identity_covers_graph_panels_beyond_preview_pixel_hash(tmp_path):
    from types import SimpleNamespace
    import json
    from twobyteasr.rendering.static_export_cache import cache_key
    font=tmp_path/'font.ttf';font.write_bytes(b'font identity')
    snapshot=SimpleNamespace(resolved_caption=SimpleNamespace(font_face_json=json.dumps(dict(file=str(font),family='Test'))),
        pixel_hash=lambda **kw:'same canonical glyph fields',
        style_recipe={'name':'label','visualGraph':{'panelLayer':{'primitive':'ROUNDED_PANEL','params':{'fill':'red'}}}})
    before=cache_key(snapshot,1920,1080)
    snapshot.style_recipe['name']='rename only'
    assert cache_key(snapshot,1920,1080)==before
    snapshot.style_recipe['visualGraph']['panelLayer']['params']['fill']='blue'
    assert cache_key(snapshot,1920,1080)!=before

def test_runtime_identity_is_computed_once_per_export_and_refreshed_next_export(monkeypatch):
    from twobyteasr.rendering import advanced_renderer as renderer
    from twobyteasr.rendering.caption_asset_identity import renderer_identity_scope
    version=['before'];calls=[]
    def compute():calls.append(version[0]);return version[0]
    monkeypatch.setattr(renderer,'_compute_renderer_cache_fingerprint',compute)
    @renderer_identity_scope
    def export():return [renderer._renderer_cache_fingerprint(),renderer._renderer_cache_fingerprint()]
    assert export()==['before','before'] and calls==['before']
    version[0]='after dependency update'
    assert export()==['after dependency update']*2 and len(calls)==2
