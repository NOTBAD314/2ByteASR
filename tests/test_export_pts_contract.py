import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from fractions import Fraction
from pathlib import Path
import pytest
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.exports.export_media import probe_media, SequentialExportDecoder, ExportMediaError
from twobyteasr.timeline.clip_time_mapper import project_to_source_exact
FFMPEG=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'

@pytest.mark.parametrize('fps',['30','60','30000/1001','60000/1001'])
def test_cfr_fractional_frames_eof_and_duration(fps,tmp_path):
    path=tmp_path/'source.mp4'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-f','lavfi','-i',f'testsrc2=s=160x90:r={fps}:d=0.5',
        '-c:v','libx264','-threads','2',str(path)],purpose='PTS regression fixture',check=True,timeout=10)
    index=probe_media(FFMPEG,path);decoder=SequentialExportDecoder(index)
    try:
        for pts in [index.pts[0],*index.pts[-3:]]:
            (_,_,pixels),receipt=decoder.read(pts*index.time_base-index.origin,context={'clip_id':'clip','timeline_frame_index':1})
            assert pixels and receipt['frame_pts']==pts and receipt['state']=='FRAME'
        # A valid decoded frame remains consumable even when decode-ahead hit EOF.
        for i in range(2):
            _,receipt=decoder.read(index.last+index.interval)
            assert receipt['frame_pts']==index.pts[-1]
        assert receipt['request_id']==6
        with pytest.raises(ExportMediaError,match='FRAME_REQUEST'):
            decoder.read(index.last+index.interval*3)
    finally:decoder.close()
    fresh = SequentialExportDecoder(index)
    try:
        _, resumed = fresh.read(index.last, context={'clip_id':'retried-clip'})
        assert resumed['generation'] != decoder.generation
        assert resumed['request_id'] == 1 and resumed['clip_id'] == 'retried-clip'
        assert resumed['state'] == 'FRAME' and resumed['frame_pts'] == index.pts[-1]
    finally:fresh.close()

def test_vfr_and_nonzero_start_keep_real_pts(tmp_path):
    path=tmp_path/'vfr.mkv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-f','lavfi','-i','testsrc2=s=160x90:r=60:d=1',
        '-vf',"select='not(mod(n,3))+eq(mod(n,7),0)',setpts=PTS+2/TB",'-fps_mode','vfr',
        '-c:v','ffv1',str(path)],purpose='VFR nonzero PTS fixture',check=True,timeout=10)
    index=probe_media(FFMPEG,path)
    assert index.origin>0 and len(set(b-a for a,b in zip(index.pts,index.pts[1:])))>1
    decoder=SequentialExportDecoder(index)
    try:
        for raw in index.pts:
            _,receipt=decoder.read(raw*index.time_base-index.origin)
            assert receipt['frame_pts']==raw
        _,a=decoder.read(Fraction(0));_,b=decoder.read(Fraction(0))
        assert a['frame_pts']==b['frame_pts']==index.pts[0]
        assert a['request_id']!=b['request_id']
    finally:decoder.close()

def test_exact_trim_and_move_mapping_before_quantization():
    clip=dict(source_in_ms=12000,source_out_ms=13000,timeline_in_ms=34000,timeline_out_ms=34500,playback_rate=2)
    assert project_to_source_exact(clip,Fraction(34000,1000))==12
    assert project_to_source_exact(clip,Fraction(34499,1000))==Fraction(12998,1000)
    assert project_to_source_exact(clip,Fraction(34500,1000)) is None

def test_damaged_media_fails_during_probe(tmp_path):
    path=tmp_path/'broken.mp4';path.write_bytes(b'not an MP4')
    with pytest.raises(ExportMediaError,match='MEDIA_PROBE'):probe_media(FFMPEG,path)
