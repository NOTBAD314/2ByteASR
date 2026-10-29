"""Container display matrices must agree with the prior FFmpeg autorotate path."""
from fractions import Fraction
from pathlib import Path
import pytest
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.playback.video_decode_worker import display_bgra


def test_padded_viewport_rows_without_numpy_import():
    import sys
    code = '''
import sys
import av
from twobyteasr.playback.video_decode_worker import display_bgra
class RejectNumpy:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'numpy' or fullname.startswith('numpy.'):
            raise AssertionError('video display must not load NumPy')
sys.meta_path.insert(0, RejectNumpy())
frame = av.VideoFrame(318, 178, 'bgra')
plane = frame.planes[0]
assert plane.line_size > 318*4
plane.update(b''.join(bytes([y % 256, 31, 211, 255])*318 + b'\\x99'*(plane.line_size-318*4) for y in range(178)))
w,h,pixels = display_bgra(frame, 1, (318,178))
assert (w,h) == (318,178)
assert pixels == b''.join(bytes([y % 256,31,211,255])*318 for y in range(178))
assert 'numpy' not in sys.modules
'''
    run_hidden_subprocess([sys.executable, '-c', code], purpose='padded viewport dependency and pixel regression',
                          capture_output=True, check=True, timeout=10)


@pytest.mark.parametrize('angle,mirror,sar',[(0,False,1),(90,False,1),(180,False,1),(270,False,1),
    (0,True,1),(90,True,1),(180,True,1),(270,True,1),(90,False,2)])
def test_metadata_pixels_match_ffmpeg_autorotate(tmp_path,angle,mirror,sar):
    import av
    import numpy as np
    source=np.zeros((48,96,3),dtype=np.uint8)
    source[:24,:48]=(255,0,0);source[:24,48:]=(0,255,0)
    source[24:,:48]=(0,0,255);source[24:,48:]=(255,255,0)
    path=tmp_path/'display.mp4'
    with av.open(str(path),'w') as output:
        stream=output.add_stream('libx264',rate=30)
        stream.width=96;stream.height=48;stream.pix_fmt='yuv420p'
        stream.sample_aspect_ratio=Fraction(sar,1)
        stream.set_display_rotation(angle,hflip=mirror)
        frame=av.VideoFrame.from_ndarray(source,format='rgb24')
        for packet in stream.encode(frame):output.mux(packet)
        for packet in stream.encode():output.mux(packet)
    with av.open(str(path)) as source_file:
        frame=next(source_file.decode(video=0))
        width,height,pixels=display_bgra(frame,float(source_file.streams.video[0].sample_aspect_ratio or 1),(1920,1080))
    ffmpeg=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    reference=run_hidden_subprocess([str(ffmpeg),'-v','error','-i',str(path),'-frames:v','1',
        '-vf',f'scale={width}:{height}', '-pix_fmt','bgra','-f','rawvideo','pipe:1'],
        purpose='compare metadata display pixels',capture_output=True,check=True,timeout=15).stdout
    actual=np.frombuffer(pixels,dtype=np.uint8).reshape(height,width,4).astype(float)
    expected=np.frombuffer(reference,dtype=np.uint8).reshape(height,width,4).astype(float)
    assert (width,height)==((48,96*sar) if angle in (90,270) else (96*sar,48))
    # Sample inside all asymmetric quadrants; resampling edges are irrelevant.
    for y in (height//4,3*height//4):
        for x in (width//4,3*width//4):
            assert abs(actual[y,x]-expected[y,x]).max()<5
