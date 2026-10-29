from types import SimpleNamespace
from twobyteasr.rendering.caption_boundary_publisher import CaptionBoundaryPublisher,BoundaryPixels


def fixture(gap=0):
    posts=[];removes=[]
    controller=SimpleNamespace(source_epoch=1,post_raw_overlay=lambda *a,**k:posts.append((a,k)),post_remove_overlay=removes.append)
    publisher=CaptionBoundaryPublisher(controller,0)
    pixels=SimpleNamespace(raw_path='owned.rgba',raw_geometry={'alpha_nonzero':12})
    for ident,start,end in [('A',0,1000),('B',1000+gap,2000)]:publisher.register('revision',BoundaryPixels(ident,start,end,pixels,{}))
    return publisher,controller,posts,removes


def observe(p,ms,**kwargs):p.observe(dict(position=ms/1000,paused=False,seeking=False,**kwargs))


def test_observation_switches_prepared_pixels_without_gui_and_preserves_gap():
    p,c,posts,removes=fixture(1)
    observe(p,999);assert posts[-1][1]['valid_when']()
    observe(p,1000);assert removes==[0] and not p.allows('A')
    assert not posts[-1][1]['valid_when']()
    observe(p,1016.666);assert p.active=='B' and posts[-1][1]['valid_when']() and not p.allows('A')
    posts[-1][1]['on_applied'](True);assert p.metrics[-1]['cue_id']=='B'
    assert len(posts)==2


def test_revision_seek_and_close_reject_inflight_work():
    p,c,posts,_=fixture();observe(p,1000);pending=posts[-1][1]['valid_when']
    c.source_epoch=2;assert not pending()
    p.register('edited',BoundaryPixels('B',1000,2000,SimpleNamespace(raw_path='new',raw_geometry={}),{}))
    assert not pending()
    observe(p,1016);pending=posts[-1][1]['valid_when'];p.close()
    assert not pending() and not p.entries


def test_overlapping_cues_keep_existing_gui_policy():
    p,c,posts,_=fixture(-100)
    observe(p,950)
    assert p.active is None and posts==[] and p.allows('A') and p.allows('B')


def test_fractional_frame_observation_does_not_round_below_real_cue_start():
    from fractions import Fraction
    p,c,posts,_=fixture(1);p.frame_rate=Fraction(60000,1001)
    observe(p,1000.9999999999)
    assert p.active=='B' and posts[-1][1]['valid_when']()


def test_identical_web_pixels_skip_ipc_but_new_identity_still_binds():
    from io import BytesIO
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from PySide6.QtCore import QRect
    from twobyteasr.rendering.live_web_preview import WebFrame
    from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
    app=QApplication.instance() or QApplication([])
    raw=BytesIO();Image.new('RGBA',(2,2),'white').save(raw,format='PNG');payload=raw.getvalue()
    bound=[];posted=[]
    overlay=SimpleNamespace(set_visual=lambda *a,**k:bound.append(a),publish_web_frame=lambda png:posted.append(png) or True,
        geometry=lambda:QRect(0,0,100,100))
    snapshot=SimpleNamespace(cue_id='A')
    page=SimpleNamespace(_web_frame_is_current=lambda _:True,_web_live_snapshot=snapshot,_web_live_cue_id='A',
        _caption_binding_options=lambda _: {},_studio_trace=lambda *a,**k:None,
        video=SimpleNamespace(_web_live_epoch=1,begin_web_live_overlays=lambda:None))
    def publish(generation=1):
        frame=WebFrame(payload,1,'content',generation,1);frame.decoded_image=QImage.fromData(payload)
        StudioAdvancedFlowMixin._publish_web_live_frame(page,frame,100,100,snapshot,overlay)
    publish();publish()
    assert len(bound)==1 and posted==[] and page._web_live_duplicate_pixels==1
    publish(2)
    assert len(bound)==2
