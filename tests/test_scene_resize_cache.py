from types import SimpleNamespace
from PySide6.QtCore import QRect
from twobyteasr.rendering.caption_scene import CaptionScene,scene_raster_geometry


def page():
    return SimpleNamespace(video=SimpleNamespace(devicePixelRatioF=lambda:1.),
        position_overlay=SimpleNamespace(video_width=1920,video_height=1080),
        project=SimpleNamespace(media=SimpleNamespace(width=1920,height=1080)),
        _advanced_preview_size=lambda:(1280,720))


def prepared(*,web=False,motion=False):
    return SimpleNamespace(web=object() if web else None,snapshot=SimpleNamespace(
        word_animation={},style_recipe={},motion_recipe={'mode':'fade' if motion else 'none'}))


def token(rect,spec):
    return (1,2,3,4,('a',),'content',spec,*rect.getRect())


def test_static_pixels_reuse_but_current_geometry_and_quality_are_distinct():
    p=page();items=[('a',prepared())]
    a,b=QRect(0,0,400,225),QRect(40,15,440,248)
    first=token(a,scene_raster_geometry(p,a,items));second=token(b,scene_raster_geometry(p,b,items))
    assert first!=second and first[-4:]!=second[-4:]
    assert CaptionScene.frame_key(first)==CaptionScene.frame_key(second)
    high=QRect(40,15,800,450)
    assert CaptionScene.frame_key(first)!=CaptionScene.frame_key(token(high,scene_raster_geometry(p,high,items)))


def test_free_html_and_motion_keep_exact_viewport_raster_identity():
    p=page();a,b=QRect(0,0,400,225),QRect(40,15,440,248)
    for item in (prepared(web=True),prepared(motion=True),None):
        first=scene_raster_geometry(p,a,[('a',item)]);second=scene_raster_geometry(p,b,[('a',item)])
        assert first[:2]==(400,225) and not first[2]
        assert CaptionScene.frame_key(token(a,first))!=CaptionScene.frame_key(token(b,second))


def test_preparation_resolution_change_never_reuses_prior_font_layout():
    p=page();r=QRect(0,0,400,225);items=[('a',prepared())]
    first=scene_raster_geometry(p,r,items)
    p._advanced_preview_size=lambda:(960,540)
    assert CaptionScene.frame_key(token(r,first))!=CaptionScene.frame_key(token(r,scene_raster_geometry(p,r,items)))
