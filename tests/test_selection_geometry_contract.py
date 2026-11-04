import io,os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PIL import Image,ImageDraw
from twobyteasr.studio.selection_geometry import alpha_bounds
from twobyteasr.playback.studio_mpv import mpv_startup_arguments

def test_native_renderer_receives_shipped_fonts():
    from pathlib import Path
    args=mpv_startup_arguments(Path('mpv.exe'),1,'pipe')
    fonts=next(a.split('=',1)[1] for a in args if a.startswith('--sub-fonts-dir='))
    assert Path(fonts).name=='fonts' and list(Path(fonts).glob('*.otf'))
    assert '--sub-ass-override=no' in args

def test_full_stage_effect_is_excluded_from_subject_geometry():
    im=Image.new('RGBA',(320,180));draw=ImageDraw.Draw(im)
    draw.rectangle((0,0,319,10),fill='white')
    draw.rectangle((100,130,220,150),fill='black')
    draw.rectangle((102,132,218,148),fill='white')
    out=io.BytesIO();im.save(out,format='PNG')
    assert alpha_bounds(out.getvalue(),[90,120,140,40])==[100,130,121,21]
    assert alpha_bounds(out.getvalue())==[0,0,320,151]


def test_missing_measured_pixels_have_no_invisible_resize_hit_target():
    from PySide6.QtCore import QPoint,QRectF
    from types import SimpleNamespace
    from twobyteasr.studio.studio_position_overlay import SubtitlePositionOverlay
    owner=SimpleNamespace(_subtitle_rect=lambda:QRectF())
    assert SubtitlePositionOverlay._handle_at(owner,QPoint(0,0))==''
