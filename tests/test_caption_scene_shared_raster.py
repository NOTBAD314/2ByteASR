"""Single-raster sharing preserves actual pixels, COW and worker retirement."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from types import SimpleNamespace
import threading
import weakref

import numpy as np
import pytest
from PySide6.QtCore import QObject,Qt
from PySide6.QtGui import QImage,QPainter,QColorSpace
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,SubtitleStyle,StudioMedia
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_style.style_recipe import RecipeRoute
from twobyteasr.rendering.caption_playback_cache import PreparedCaption
from twobyteasr.rendering.caption_scene import SceneRasterizer,CaptionScene,animated_caption,FRAME_CACHE_BYTES


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def items(count=1,effect='none'):
    project=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=2000,width=1920,height=1080),
        cues=[StudioCue('cue-'+str(i),0,1800,
        '字幕完整显示 '+str(i) if i==0 else 'A bilingual translation '+str(i),style_id='s'+str(i),effect_id=effect)
        for i in range(count)],styles=[SubtitleStyle('s'+str(i),'s'+str(i),font_size=42,
            position_x=960,position_y=750+100*i) for i in range(count)])
    result=[]
    for cue in project.cues:
        snapshot=build_visual_cue_snapshot(project,cue.id,width=640,height=360)
        result.append((cue.id,PreparedCaption(snapshot,snapshot.stable_hash(),RecipeRoute('native',()))))
    return project,tuple(result)


def pixels(image):return bytes(image.constBits())


def reference_composite(renderer,prepared,time_ms,width,height):
    """Independent transparent source-over composition contract before sharing."""
    output=QImage(width,height,QImage.Format_ARGB32_Premultiplied);output.fill(Qt.transparent)
    painter=QPainter(output);rows=[]
    for cue_id,item in prepared:
        snapshot=item.snapshot;relative=max(0,time_ms-snapshot.start_ms)
        image=renderer.native_frame(item,relative,width,height)
        gesture=item.interaction_transform
        painter.save()
        if gesture:
            px=width/snapshot.playres_x;py=height/snapshot.playres_y
            painter.translate(gesture['position_x']*px,gesture['position_y']*py)
            painter.rotate(gesture.get('rotation',snapshot.rotation)-snapshot.rotation)
            painter.scale(gesture['scale_x']/100/snapshot.scale_x,gesture['scale_y']/100/snapshot.scale_y)
            painter.translate(-snapshot.position_x*px,-snapshot.position_y*py)
        painter.drawImage(output.rect(),image);painter.restore()
        rgba=image.convertToFormat(QImage.Format_RGBA8888)
        alpha=np.ndarray((height,width,4),dtype=np.uint8,buffer=rgba.constBits(),strides=(rgba.bytesPerLine(),4,1))[:,:,3]
        ys=np.flatnonzero(np.any(alpha,axis=1));xs=np.flatnonzero(np.any(alpha,axis=0))
        rows.append(dict(cue_id=cue_id,status='rendered',snapshot_hash=item.snapshot_hash,route='native',
            position=[snapshot.position_x,snapshot.position_y],local_ms=float(relative),alpha_nonzero=int(np.count_nonzero(alpha)),
            bounds=[int(xs[0]),int(ys[0]),int(xs[-1]-xs[0]+1),int(ys[-1]-ys[0]+1)] if len(xs) and len(ys) else None,
            viewport=[width,height]))
    painter.end();return output,rows


@pytest.mark.parametrize('kind,time_ms',[('single',500),('bilingual',500),('gesture',500),
    ('fade',0),('fade',90),('fade',250),('fade',1000),('fade',1750),('empty',0)])
def test_real_pixels_and_metadata_match_transparent_composition(app,kind,time_ms):
    _project,prepared=items(2 if kind=='bilingual' else 1,'fade' if kind=='fade' else 'none')
    if kind=='gesture':
        cue_id,item=prepared[0]
        prepared=((cue_id,replace(item,interaction_transform=dict(position_x=900,position_y=850,scale_x=120,scale_y=90,rotation=12))),)
    if kind=='empty':prepared=()
    if kind=='fade':assert animated_caption(prepared[0][1])
    expected_renderer=SceneRasterizer();renderer=SceneRasterizer()
    try:
        expected,expected_rows=reference_composite(expected_renderer,prepared,time_ms,640,360)
        actual,rows=renderer.frame(prepared,time_ms,640,360)
        assert pixels(actual)==pixels(expected)
        assert rows==expected_rows and actual.devicePixelRatio()==expected.devicePixelRatio()
        assert actual.colorSpace()==expected.colorSpace()
        if kind=='single':
            native=next(iter(renderer.rasters.values()))[2]
            assert actual is not native and actual.cacheKey()==native.cacheKey()
        else:
            assert all(actual.cacheKey()!=value[2].cacheKey() for value in renderer.rasters.values() if value[2] is not None)
    finally:expected_renderer.close();renderer.close()


def test_return_wrapper_detaches_and_holders_survive_cache_clear(app):
    _,prepared=items();renderer=SceneRasterizer()
    actual,_=renderer.frame(prepared,500,640,360);native=next(iter(renderer.rasters.values()))[2]
    before=pixels(native);held=QImage(actual)
    assert actual is not native and actual.cacheKey()==native.cacheKey()
    actual.fill(Qt.red)
    assert pixels(native)==before and pixels(held)==before
    renderer.close()
    assert pixels(held)==before


def test_image_metadata_outside_fast_path_uses_original_canvas(app,monkeypatch):
    _,prepared=items();renderer=SceneRasterizer()
    native=QImage(640,360,QImage.Format_ARGB32_Premultiplied);native.fill(Qt.blue)
    native.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    monkeypatch.setattr(renderer,'native_frame',lambda *args:native)
    actual,_=renderer.frame(prepared,500,640,360)
    assert actual.cacheKey()!=native.cacheKey()
    assert not actual.colorSpace().isValid()


def test_actual_raw_pixel_packing_keeps_shared_source_immutable(app,monkeypatch,tmp_path):
    from contextlib import nullcontext
    from twobyteasr.rendering.caption_pixel_cache import prepared_pixels
    from twobyteasr.rendering import overlay_session
    # File bytes/cropping are real; this unit needs no asynchronous storage
    # service. Its lease-close behavior is separately covered by retirement.
    monkeypatch.setattr(overlay_session,'lease_overlay_deferred',lambda *args:nullcontext())
    _,prepared=items();renderer=SceneRasterizer()
    image,_=renderer.frame(prepared,500,640,360)
    native=next(iter(renderer.rasters.values()))[2];before=pixels(native)
    packed=prepared_pixels(image,None,0,raw_folder=tmp_path)
    assert image is not native and packed.image.cacheKey()==native.cacheKey()
    assert pixels(native)==before and packed.raw_path.stat().st_size==packed.raw_geometry['bytes']
    renderer.close()
    assert pixels(packed.image)==before


def worker_scene(project):
    page=QObject();page.project=project
    page.video=SimpleNamespace(_compositor_overlay_dir=None,_playback_clock=SimpleNamespace(generation=1))
    page._revision_store=SimpleNamespace(render=SimpleNamespace(mapping_revision=1,visual_revision=1))
    scene=CaptionScene(page);scene.ready.disconnect(scene.accept)
    return page,scene


def dispose_worker(page,scene):
    # Explicitly release fixture QObjects on the test's GUI thread instead of
    # leaving their parent/child Python cycle to interpreter shutdown.
    from shiboken6 import delete
    scene.close();scene.thread.join(3)
    assert not scene.thread.is_alive()
    page.destroyed.disconnect(scene.close)
    scene.destroyed.disconnect(scene.close)
    scene.ready.disconnect()
    delete(scene);delete(page)


def test_real_worker_caches_share_buffers_and_cancelled_generation_cannot_publish(app,monkeypatch):
    project,prepared=items(4);page,scene=worker_scene(project)
    observed=[]
    # work() may already have created its rasterizer; capture it by the actual
    # frame method, without replacing rendering or the cache insertion path.
    old_frame=SceneRasterizer.frame
    def frame(self,*args,**kwargs):
        if not observed:observed.append(weakref.ref(self))
        return old_frame(self,*args,**kwargs)
    monkeypatch.setattr(SceneRasterizer,'frame',frame)
    ready=threading.Event();delivery=[]
    def delivered(token,pixel,trace):
        delivery.append((token,pixel,trace));ready.set()
    scene.ready.connect(delivered,Qt.DirectConnection)
    try:
        for index,item in enumerate(prepared):
            token=(id(project),1,1,1,(item[0],),index,(640,360,False,None),0,0,640,360)
            ready.clear()
            with scene.lock:scene.pending=(token,(item,),500,640,360);scene.token=token;scene.wake.set()
            assert ready.wait(3)
            with scene.lock:pass
        rasterizer=observed[0]()
        inner=[value[2] for value in rasterizer.rasters.values()]
        outer=[value[0].image for value in scene.frames.values()]
        assert len(inner)==len(outer)==4 and FRAME_CACHE_BYTES==64*1024*1024
        assert {image.cacheKey() for image in inner}=={image.cacheKey() for image in outer}
        token,pixel,trace=delivery[-1];held=QImage(pixel.image);before=pixels(held)
        page.video._playback_clock.generation=2
        scene.accept(token,pixel,trace)
        assert scene.published is None and scene.metrics==[]
        with scene.lock:scene.frames.clear();rasterizer.close()
        assert pixels(held)==before
    finally:
        dispose_worker(page,scene)


def test_close_during_real_render_rejects_late_result_and_retires_inner_cache(app,monkeypatch):
    project,prepared=items();entered=threading.Event();release=threading.Event();observed=[]
    original=SceneRasterizer.frame
    def delayed(self,*args,**kwargs):
        value=original(self,*args,**kwargs);observed.append(self);entered.set()
        assert release.wait(3)
        return value
    monkeypatch.setattr(SceneRasterizer,'frame',delayed)
    page,scene=worker_scene(project);delivered=[]
    def received(*args):delivered.append(True)
    scene.ready.connect(received,Qt.DirectConnection)
    token=(id(project),1,1,1,(prepared[0][0],),0,(640,360,False,None),0,0,640,360)
    try:
        with scene.lock:scene.pending=(token,prepared,500,640,360);scene.token=token;scene.wake.set()
        assert entered.wait(3)
        scene.close();release.set();scene.thread.join(3)
        assert not scene.thread.is_alive() and delivered==[] and not scene.frames
        assert observed and not observed[0].rasters
    finally:release.set();dispose_worker(page,scene)
