"""The native presentation contract, including alpha, slot ownership and cleanup."""
from types import SimpleNamespace

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio.studio_video_canvas import MpvCanvas
from twobyteasr.playback.video_compositor import VideoCompositionScene
from twobyteasr.playback.secondary_video import SourceState

APP = QApplication.instance() or QApplication([])


class NativeSurface(QWidget):
    def __init__(self):
        super().__init__()
        self.frames = {}
        self.posts = 0

    def publish_compositor_overlay(self, slot, frame, rect, **kwargs):
        self.frames[slot] = frame.copy()
        self.posts += 1
        return True

    def remove_compositor_overlay(self, slot, **kwargs):
        self.frames.pop(slot, None)


def test_scene_publishes_latest_pixels_and_clears_hidden_or_stale_frames():
    host = NativeSurface()
    host.resize(320, 180)
    scene = VideoCompositionScene(host)
    scene.resize(host.size())
    frame = QImage(320, 180, QImage.Format.Format_ARGB32)
    frame.fill(QColor('red'))
    runtime = SimpleNamespace(image=frame, pts_ms=1000, frame_age_ms=0, generation=1)
    scene._players['v2'] = runtime
    scene._layers = [{'clip_id': 'v2', 'source_ms': 1000, 'transform': {'opacity': .5}}]
    scene.set_selected_clip('v2')
    host.show()
    scene.show()
    QTest.qWait(80)
    video = host.frames[MpvCanvas.VIDEO_OVERLAY_ID]
    assert video.pixelColor(160, 90).alpha() in (127, 128)
    assert MpvCanvas.VIDEO_TRANSFORM_OVERLAY_ID in host.frames

    frame.fill(QColor('blue'))
    scene.update()
    QTest.qWait(80)
    assert host.frames[MpvCanvas.VIDEO_OVERLAY_ID].pixelColor(160, 90).blue() == 255

    # A late frame outside tolerance must not leave yesterday's bitmap visible.
    runtime.pts_ms = 10000
    runtime.frame_age_ms = 5000
    scene.update()
    QTest.qWait(80)
    assert not host.frames
    runtime.pts_ms = 1000
    scene.repaint()  # queues a native publish, then hide must cancel it
    scene.hide()
    posts = host.posts
    QTest.qWait(80)
    assert not host.frames and host.posts == posts
    scene._players.clear()
    host.close()
    host.deleteLater()


def test_raw_bridge_premultiplies_alpha_and_video_removal_preserves_web_session(tmp_path):
    canvas = MpvCanvas()
    captured = []
    canvas.controller = SimpleNamespace(
        running=True,
        post_raw_overlay=lambda slot, path, **kw: captured.append(path.read_bytes()) or True,
        post_remove_overlay=lambda slot: True,
    )
    canvas._media_attached = True
    canvas._compositor_overlay_dir = tmp_path
    frame = QImage(2, 2, QImage.Format.Format_ARGB32)
    frame.fill(QColor(200, 100, 50, 128))
    assert canvas.publish_compositor_overlay(canvas.VIDEO_OVERLAY_ID, frame, QRect(0, 0, 2, 2))
    assert list(captured[-1][:4]) == [25, 50, 100, 128]
    canvas._web_live_epoch = 7
    canvas._web_live_overlay_active = True
    canvas.remove_compositor_overlay(canvas.VIDEO_OVERLAY_ID, force=True)
    assert canvas._web_live_epoch == 7 and canvas._web_live_overlay_active
    assert canvas.VIDEO_OVERLAY_ID < canvas.ADVANCED_OVERLAY_ID < canvas.TRANSFORM_OVERLAY_ID
    assert canvas.TRANSFORM_OVERLAY_ID < canvas.VIDEO_TRANSFORM_OVERLAY_ID


def test_selection_handles_queue_io_and_revoke_on_hide(tmp_path):
    canvas=MpvCanvas();queued=[];revoked=[];direct=[]
    canvas.controller=SimpleNamespace(running=True,
        post_raw_overlay=lambda *args,**kwargs:direct.append(args),post_remove_overlay=lambda *args:True)
    canvas._media_attached=True
    canvas._subtitle_raster_publisher=SimpleNamespace(
        submit=lambda *args,**kwargs:queued.append((args,kwargs)) or True,
        revoke=revoked.append)
    frame=QImage(40,20,QImage.Format_ARGB32);frame.fill(QColor('red'))
    assert canvas.publish_compositor_overlay(canvas.TRANSFORM_OVERLAY_ID,frame,QRect(10,30,40,20),
        context={'caller':'SubtitlePositionOverlay._publish_to_mpv'})
    assert len(queued)==1 and not direct
    canvas.remove_compositor_overlay(canvas.TRANSFORM_OVERLAY_ID,force=True)
    assert canvas.TRANSFORM_OVERLAY_ID in revoked
    canvas._subtitle_raster_publisher=None;canvas.controller=None
    canvas.close();canvas.deleteLater()
    canvas.controller = None
    canvas.deleteLater()


def test_lone_secondary_layer_in_primary_gap_still_requires_subtitle_promotion(monkeypatch):
    class Decoder(QObject):
        frame_updated = Signal()
        state = SourceState.IDLE

        def set_preview_size(self, *args):
            pass

        def prepare(self, path):
            self._pending_path = path

        def request_frame(self, *args, **kwargs):
            pass

        def release(self):
            pass

        def suspend(self):
            pass

    monkeypatch.setattr('twobyteasr.playback.video_compositor.SecondaryVideoSource', Decoder)
    scene = VideoCompositionScene()
    scene.set_composition(
        [{'clip_id': 'v2', 'track_id': 'V2', 'source_path': 'secondary.mp4'}],
        paused=True, rate=1, audio_master_track_id='', base_track_id='V2',
        volume=0, mpv_path='primary.mp4',
    )
    assert scene.has_video_overlays
    scene.suspend()
    assert not scene.has_video_overlays
    scene.clear()
    scene.deleteLater()
