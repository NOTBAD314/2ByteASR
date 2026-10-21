"""Subject evidence and authored-frame ownership, including failure paths."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
import pytest
from PIL import Image


def test_motion_uses_one_subject_envelope_and_separate_context(tmp_path,monkeypatch):
    from twobyteasr.caption_design.theme_direction_preview import render_motion_preview
    from PIL import ImageDraw
    import twobyteasr.system.processes as process
    import twobyteasr.playback.audio_engine as audio
    monkeypatch.setattr(process,'run_hidden_subprocess',lambda *a,**k:None)
    monkeypatch.setattr(audio,'studio_ffmpeg_path',lambda:'ffmpeg')
    background=tmp_path/'game.png';Image.new('RGBA',(960,540),'red').save(background)
    class Renderer:
        def live_set(self,*a,**k):pass
        def live_pause(self,*,cue_ms,**k):
            im=Image.new('RGBA',(960,540));draw=ImageDraw.Draw(im)
            x=200+round(cue_ms/20);draw.rectangle((x,300,x+200,400),fill='#a4e5f0')
            stream=BytesIO();im.save(stream,format='PNG');return stream.getvalue()
    motion=render_motion_preview(Renderer(),'',tmp_path,'ice',duration_ms=1500,background_path=background)
    assert motion['presentation']=='subject' and not motion['full_frame']
    assert motion['background']=='neutral' and motion['context']['background']=='current-media'
    images=[Image.open(tmp_path/'ice-frames'/f'{i:04}.png') for i in (0,17,35)]
    assert len({im.size for im in images})==1 and images[0].size[1]<540
    assert all(im.getpixel((0,0))==(32,38,46) for im in images)
    assert Image.open(tmp_path/'ice-context-frames/0000.png').getpixel((0,0))==(255,0,0)


def test_ice_expands_into_valid_safe_single_clock_theme():
    from twobyteasr.caption_design.caption_components import compose
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    for geometry in ('shelf','facet'):
        theme=WebThemeDocument.from_dict(dict(name='冰川',**compose(dict(version=6,geometry=geometry))))
        assert 'ice-crack' in theme.cue_html and 'mix-blend-mode:screen' in theme.cue_css
        assert 'animation:' not in theme.cue_css
        assert theme.motion_spec['version']==2


def test_material_search_and_prompt_route_preserve_user_theme():
    from twobyteasr.caption_design.caption_reference_search import queries_for
    from twobyteasr.caption_design.caption_reference_catalog import component_style
    from twobyteasr.caption_design.caption_components import capability_text
    from twobyteasr.caption_design.design_guidance import load_design_guidance
    assert 'animated captions' in queries_for('冰河世纪主题')[0]
    assert component_style('冰河世纪主题')=='ice'
    assert 'version:7' in capability_text('ice')
    guidance,receipt=load_design_guidance('冰河世纪主题')
    assert '材料如何形成' in guidance and 'Captioneer' in guidance
    assert any(row['path'].endswith('material-caption.md') for row in receipt['files'])


def test_web_never_publishes_ordinary_qt_mirror_even_when_pending():
    from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
    snapshot=SimpleNamespace(style_recipe={'webTheme':{'cueHtml':'<div/>'}})
    # No widget exists: a mirror must be rejected before touching any painter.
    page=SimpleNamespace()
    assert StudioAdvancedFlowMixin._publish_advanced_live(page,snapshot,None)==0
    assert StudioAdvancedFlowMixin._commit_advanced_live(page,None,snapshot,None,'',False,12)==12


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def project():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,SubtitleStyle,StudioMedia
    return SubtitleProject(media=StudioMedia('',width=600,height=480,duration_ms=3000),
        styles=[SubtitleStyle('plain','Plain'),SubtitleStyle('ice','Ice')],
        cues=[StudioCue('p',0,1000,'普通字幕',style_id='plain'),StudioCue('w',1000,2000,'特效正文',style_id='ice'),StudioCue('n',2000,3000,'下一句',style_id='plain')],
        style_recipes={'ice':{'name':'Ice','engine':'remotion','webTheme':{'cueHtml':'<div>{{text}}</div>'}}})


def test_ass_event_exclusion_prevents_pts_boundary_flash(app):
    from twobyteasr.studio.studio_ass_flow import StudioAssFlowMixin
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    p=project();page=SimpleNamespace(project=p,_revision_store=StudioRevisionStore(p),_subtitle_track_visibility={},
        timeline=SimpleNamespace(hidden_speakers=set()),_advanced_ass_hidden=set(),_live_edit_text_overrides={},_live_transform_overrides={},_studio_trace=lambda *a,**k:None)
    revision=StudioAssFlowMixin._ass_preview_revision(page)
    assert [c.id for c in revision.cues]==['p','n']
    assert page._advanced_ass_hidden=={'w'}
    assert [c.id for c in p.cues]==['p','w','n']


def test_failed_web_preparation_has_no_plain_fallback(app):
    from twobyteasr.rendering.caption_playback_cache import basic_caption
    assert basic_caption(project(),'w',600,480,'browser failed') is None
    assert basic_caption(project(),'p',600,480,'other failure') is not None


def test_failed_web_raster_does_not_draw_default_text(app):
    from twobyteasr.rendering.caption_scene import SceneRasterizer
    from twobyteasr.rendering.caption_playback_cache import PreparedCaption
    from twobyteasr.caption_style.style_recipe import RecipeRoute
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    p=project();snapshot=build_visual_cue_snapshot(p,'p',width=600,height=480)
    ready=PreparedCaption(snapshot,snapshot.stable_hash(),RecipeRoute('remotion',()),web=object())
    renderer=SceneRasterizer()
    image,rows=renderer.frame([('w',ready)],1500,600,480)
    assert rows[0]['status']=='failed' and rows[0]['hidden_until_ready']
    assert image.pixelColor(300,420).alpha()==0
    assert not any(bytes(image.constBits()))


def test_candidate_card_prefers_subject_over_video(app,tmp_path):
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog,FittedPicture
    subject=tmp_path/'subject.png';video=tmp_path/'game.png'
    Image.new('RGBA',(320,180),'blue').save(subject);Image.new('RGBA',(320,180),'red').save(video)
    dialog=ThemeConceptDialog([dict(id='a',name='冰川',full_frame_preview=str(video),preview_receipt={'picture':str(subject)})],{'a':str(subject)})
    picture=dialog.findChild(FittedPicture,'subtitleSubjectPreview')
    assert picture.original.toImage().pixelColor(0,0).name()=='#0000ff'
    dialog.close()


def test_subject_zoom_can_inspect_native_pixels(app,tmp_path):
    from twobyteasr.caption_design.theme_concept_dialog import SubjectPreviewDialog
    from PySide6.QtWidgets import QSlider,QScrollArea
    path=tmp_path/'subject.png';Image.new('RGB',(400,120),'blue').save(path)
    dialog=SubjectPreviewDialog(dict(name='Ice'),str(path))
    slider=dialog.findChild(QSlider);slider.setValue(150)
    assert dialog.findChild(QScrollArea).widget().pixmap().width()==600
    slider.setValue(50)
    assert dialog.findChild(QScrollArea).widget().pixmap().width()==200
    dialog.close()


def test_boundary_retirement_releases_native_debounce_without_removing_next_overlay(app):
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    calls=[]
    controller=SimpleNamespace(running=True,_caption_boundary_publisher=SimpleNamespace(allows=lambda cue:cue=='next'),
        post_set_subtitle_visible=lambda visible:calls.append(('native',visible)) or True,
        post_remove_overlay=lambda *a,**k:calls.append(('remove',a)) or True)
    canvas=MpvCanvas();canvas.controller=controller
    slot=canvas.ADVANCED_OVERLAY_ID
    canvas._active_compositor_overlays.add(slot)
    canvas._compositor_overlay_contexts[slot]={'cue_id':'old','cue_active':False}
    canvas._web_live_overlay_active=True
    try:
        assert canvas.remove_compositor_overlay(slot,context={'cue_id':'old','cue_active':False})
        canvas.set_native_subtitle_visible(True)
        assert calls==[('native',True)]
        assert slot not in canvas._active_compositor_overlays
        assert not canvas._web_live_overlay_active
        # A late hide from the old cue must not erase the new cue's local state.
        canvas._active_compositor_overlays.add(slot)
        canvas._compositor_overlay_contexts[slot]={'cue_id':'next','cue_active':False}
        assert not canvas.remove_compositor_overlay(slot,context={'cue_id':'old','cue_active':False})
        assert canvas._compositor_overlay_contexts[slot]['cue_id']=='next'
    finally:canvas.controller=None;canvas.close()
