"""Advanced output owns the same font bytes as the resolved preview."""
import base64,hashlib,json
from pathlib import Path
from types import SimpleNamespace
from twobyteasr.rendering.export_font_assets import font_asset
from twobyteasr.caption_style.font_metadata import local_faces


def face_file():
    return next(f for f in local_faces() if Path(f.file).suffix.lower() in {'.ttf','.otf'})


def snapshot(file,family='Private export alias'):
    resolved=SimpleNamespace(font_face_json=json.dumps(dict(file=str(file),weight=500,style='Regular')))
    return SimpleNamespace(resolved_caption=resolved,font_family=family,font_weight=500)


def test_composition_owns_font_bytes_after_source_changes(tmp_path):
    original=face_file();file=tmp_path/('private'+Path(original.file).suffix)
    data=Path(original.file).read_bytes();file.write_bytes(data)
    a=font_asset(snapshot(file));b=font_asset(snapshot(file))
    assert a==b and a['sha256']==hashlib.sha256(data).hexdigest()
    assert base64.b64decode(a['source'].split(',',1)[1])==data
    file.unlink()
    assert base64.b64decode(a['source'].split(',',1)[1])==data


def test_non_font_file_cannot_be_embedded(tmp_path):
    file=tmp_path/'not-a-font.ttf';file.write_text('private non-font data')
    assert font_asset(snapshot(file)) is None


def test_existing_collection_face_keeps_system_font_route(tmp_path):
    file=tmp_path/'collection.ttc';file.write_bytes(b'ttcf')
    assert font_asset(snapshot(file)) is None


def test_explicit_override_of_a_bundled_name_owns_its_bytes(tmp_path):
    original=face_file();file=tmp_path/('private'+Path(original.file).suffix)
    file.write_bytes(Path(original.file).read_bytes())
    assert font_asset(snapshot(file,family='Cubic 11')) is not None


def test_job_freezes_a_repeated_face_once_even_without_persistent_cache(monkeypatch):
    import twobyteasr.rendering.export_font_assets as assets
    from twobyteasr.rendering.advanced_renderer import compile_composition_data
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    p=SubtitleProject(StudioMedia('',duration_ms=6000,width=1920,height=1080),
        cues=[StudioCue(str(i),i*2000,(i+1)*2000,'Export font '+str(i))for i in range(3)])
    p.validate();p.styles[0].font_family='Arial'
    p.style_recipes['default']=StyleRecipe(name='gradient',colors={'fill':{
        'type':'linear-gradient','stops':[{'offset':0,'color':'#FFFF0000'},{'offset':1,'color':'#FF0000FF'}]}}).to_dict()
    calls=[];original=assets.font_asset
    def capture(s):calls.append(s.font_family);return original(s)
    monkeypatch.setattr(assets,'_BUDGET',0);monkeypatch.setattr(assets,'font_asset',capture)
    props=compile_composition_data(p,width=1920,height=1080,fps=30.,start_seconds=0,duration_seconds=6)
    assert len(calls)==1 and len(props['fontFaces'])<=1
