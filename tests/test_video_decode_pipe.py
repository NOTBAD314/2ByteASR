import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.playback.secondary_video import SecondaryVideoSource, SourceState
from twobyteasr.playback.video_decode_pipe import VideoDecodePipe

FFMPEG = Path(__file__).resolve().parents[1] / "tools/ffmpeg/bin/ffmpeg.exe"
pytestmark = pytest.mark.skipif(not FFMPEG.is_file(), reason="bundled ffmpeg required")


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    target = tmp_path_factory.mktemp("pipe") / "双色素材.mkv"
    run_hidden_subprocess([str(FFMPEG), "-y", "-v", "error", "-f", "lavfi", "-i",
                           "color=red:s=160x90:r=60:d=1", "-f", "lavfi", "-i",
                           "color=blue:s=160x90:r=60:d=1", "-filter_complex",
                           "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264", str(target)],
                          purpose="decoder fixture", check=True, timeout=20)
    return str(target)


def wait_for(predicate, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app = QApplication.instance()
        if app:
            app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("decoder did not converge")


def test_seek_pause_latest_epoch_and_close(media):
    app = QApplication.instance() or QApplication([])
    source = SecondaryVideoSource()
    try:
        source.prepare(media)
        source.request_frame(200, paused=True, seek=True)
        wait_for(lambda: source.pts_ms == 200)
        assert source.image.pixelColor(40, 40).red() > 240
        cache = source.image.cacheKey()
        for _ in range(10):
            source.request_frame(200, paused=True, seek=True)
            app.processEvents()
        assert source.image.cacheKey() == cache
        for ms in (1300, 100, 1500):
            source.request_frame(ms, paused=True, seek=True)
        wait_for(lambda: source.pts_ms == 1500)
        assert source.image.pixelColor(40, 40).blue() > 240
        assert source._image_generation == source.generation
        assert source.audio_output_attached is False
        assert source.performance_snapshot()["mailbox_frames"] <= 1
        source.suspend()
        assert source.image.isNull()
        source.request_frame(300, paused=True, seek=True)
        wait_for(lambda: source.pts_ms == 300 and not source.image.isNull())
    finally:
        started = time.monotonic()
        source.release()
        assert time.monotonic() - started < 1.2
        assert source.thread_stopped and source.shutdown_acknowledged
        source.release()


def test_child_kill_recovers_and_buffer_is_bounded(media):
    pipe = VideoDecodePipe(FFMPEG)
    try:
        pipe.request(media, 0, 1, False, 2.)
        wait_for(lambda: pipe.snapshot()["decoded"] > 0)
        assert pipe.snapshot()["mailbox_frames"] == 1
        with pipe._condition:
            pipe._process.kill()
        pipe.request(media, 200, 1, False, 2.)
        wait_for(lambda: pipe.snapshot()["starts"] >= 2 and pipe.snapshot()["pts_ms"] >= 200)
        assert pipe.snapshot()["failures"] >= 1
        assert pipe.snapshot()["mailbox_frames"] <= 1
    finally:
        assert pipe.close()


def test_cancel_releases_decoder_and_resume_reuses_the_bounded_process(media):
    pipe=VideoDecodePipe(FFMPEG)
    try:
        pipe.request(media,200,1,True,1.)
        wait_for(lambda:pipe.snapshot().get('pts_ms')==200)
        pid=pipe.snapshot()['pid']
        pipe.cancel()
        wait_for(lambda:pipe.snapshot().get('state')=='IDLE' and pipe.snapshot().get('decoder_releases',0)==1)
        assert pipe.take_frame() is None
        pipe.request(media,1500,2,True,1.)
        wait_for(lambda:pipe.snapshot().get('pts_ms')==1500)
        frame=pipe.take_frame()
        assert frame and frame.generation==2 and frame.pixels[0]>240
        assert pipe.snapshot()['pid']==pid and pipe.snapshot()['opens']==2
    finally:
        assert pipe.close()


def test_opt_in_pixel_costs_keep_real_stage_order_and_owned_buffer(media):
    from twobyteasr.diagnostics import playback_probe
    token = playback_probe.configure(enabled=True, light=True)
    pipe = VideoDecodePipe(max_size=(80, 45))
    try:
        pipe.request(media, 200, 1, True, 1.)
        wait_for(lambda: pipe.snapshot().get('pts_ms') == 200)
        frame = pipe.take_frame()
        assert frame and frame.costs
        assert frame.costs['raster_pixels'] == [80, 45]
        assert frame.costs['pixel_bytes'] == len(frame.pixels) == 80*45*4
        assert frame.decoded_at <= frame.costs['convert_started_at'] <= frame.costs['converted_at']
        assert frame.costs['converted_at'] <= frame.published_at <= frame.write_started_at <= frame.received_at
        assert pipe.snapshot()['pixel_cost_scope'] == 'last completed frame; not a percentile'
    finally:
        pipe.close()
        playback_probe.restore(token)


def test_pause_and_rate_changes_preserve_the_worker_epoch_and_source_progress(media):
    pipe=VideoDecodePipe(FFMPEG)
    try:
        pipe.request(media,200,7,True,1.)
        wait_for(lambda:pipe.snapshot().get('pts_ms')==200)
        initial=pipe.snapshot()
        pipe.request(media,200,7,False,1.)
        wait_for(lambda:pipe.snapshot().get('pts_ms',0)>=250)
        paused_at=pipe.snapshot()['pts_ms']
        pipe.request(media,paused_at,7,True,1.)
        pipe.request(media,paused_at,7,False,4.)
        wait_for(lambda:pipe.snapshot().get('pts_ms',0)>=paused_at+150)
        current=pipe.snapshot();frame=pipe.take_frame()
        assert current['pid']==initial['pid'] and current['epoch']==initial['epoch']
        assert current['opens']==initial['opens']==1
        assert frame and frame.generation==7 and frame.pts_ms>=paused_at+150
        assert current['mailbox_frames']<=1
    finally:
        assert pipe.close()


def test_clock_pause_resume_does_not_become_a_seek(media):
    app = QApplication.instance() or QApplication([])
    source = SecondaryVideoSource()
    try:
        source.prepare(media)
        source.request_frame(200, paused=True, rate=2., seek=True, seek_token=9)
        wait_for(lambda: source.pts_ms == 200)
        generation = source.generation
        for target, paused in ((250, False), (245, True), (280, False), (275, True), (350, False)):
            source.request_frame(target, paused=paused, rate=2., seek_token=9)
            for _ in range(6):
                app.processEvents();time.sleep(.005)
        wait_for(lambda: source.pts_ms >= 333)
        assert source.generation == generation
        assert source.performance_snapshot()['starts'] == 1
        pts = [row['pts_ms'] for row in source.samples]
        assert pts == sorted(set(pts))
        source.request_frame(80, paused=True, rate=2., seek=True, seek_token=10)
        # 80ms is between real 60fps frames; never relabel decoded pixels as
        # the requested time. The newest frame not after demand is 67ms.
        wait_for(lambda: source.pts_ms == 67)
        assert source.generation == generation + 1
    finally:
        source.release()


def test_invalid_source_retries_are_bounded_then_new_epoch_recovers(media, tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    pipe = VideoDecodePipe(FFMPEG)
    try:
        pipe.request(str(bad), 0, 0, True, 1.)
        wait_for(lambda: pipe.snapshot()["state"] == 'FAILED')
        first = pipe.snapshot()
        time.sleep(.3)
        assert pipe.snapshot()['starts'] == first['starts'] == 1
        assert first['failures'] <= 3 and first['error']
        pipe.request(media, 1200, 1, True, 1.)
        wait_for(lambda: pipe.snapshot()["pts_ms"] == 1200)
        frame = pipe.take_frame()
        assert frame and frame.generation == 1 and frame.pixels[0] > 240
    finally:
        assert pipe.close()
