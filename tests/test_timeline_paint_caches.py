"""Raster reuse must follow decoded pixels, scale and viewport geometry."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from twobyteasr.studio.video_filmstrip import FilmstripCache

APP=QApplication.instance() or QApplication([])


def test_background_media_refinements_merge_during_canvas_gesture(monkeypatch):
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    timeline=WaveformTimeline();updates=[]
    monkeypatch.setattr(timeline,'update',lambda *args:updates.append(args))
    timeline.set_caption_transform_active(True)
    for index in range(20):timeline._media_refinement_ready(str(index))
    timeline.set_waveform_state('READY')
    assert timeline.waveform_state=='READY' and updates==[]
    # Direct interactive redraws are still immediate.
    timeline.update();assert len(updates)==1
    timeline.set_caption_transform_active(False);assert len(updates)==2
    timeline.set_caption_transform_active(False);assert len(updates)==2
    timeline._media_refinement_ready('later');assert len(updates)==3
    timeline.close()


def test_cell_raster_reuses_pixels_and_refreshes_after_decode_refinement(tmp_path,monkeypatch):
    cache=FilmstripCache(cache_root=tmp_path/'filmstrip');cache.set_paused(True)
    image=QPixmap(128,72);image.fill(QColor('red'))
    monkeypatch.setattr(cache,'get',lambda *_a,**_k:image)
    def paint(dpr=1.,height=40):
        surface=QPixmap(round(400*dpr),round(60*dpr));surface.setDevicePixelRatio(dpr);surface.fill(Qt.black)
        painter=QPainter(surface)
        cache.paint(painter,QRectF(0,0,400,height),'source',0,400,0,5000)
        painter.end()
        return surface.toImage()
    try:
        first=paint();keys=set(cache._cell_rasters)
        assert paint()==first and set(cache._cell_rasters)==keys
        assert first.pixelColor(30,20).red()>200
        image=QPixmap(128,72);image.fill(QColor('blue'))
        refined=paint()
        assert refined!=first and refined.pixelColor(30,20).blue()>200
        assert set(cache._cell_rasters)>keys
        paint(1.75);paint(1.75,50)
        assert any(k[3]==1.75 for k in cache._cell_rasters)
        assert cache._cell_raster_bytes<=cache._cell_raster_limit
    finally:cache.close();cache.thread.join(2)


def test_wide_timeline_playhead_pixels_change_between_subpixel_clock_samples():
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    t=WaveformTimeline();t.resize(1400,200)
    t.set_project(SubtitleProject(StudioMedia('missing.mp4',duration_ms=3000000),cues=[StudioCue('a',0,3000000,'字幕')]))
    t.set_visible_window(0,150000)
    try:
        a=next(ms for ms in range(10000,10120) if round(t._time_to_x(ms))==round(t._time_to_x(ms+16)))
        def strip(ms):
            dpr=1.75
            surface=QPixmap(round(t.width()*dpr),round(t.height()*dpr));surface.setDevicePixelRatio(dpr);surface.fill(Qt.transparent)
            painter=QPainter(surface);painter.setRenderHint(QPainter.Antialiasing)
            t.playhead_ms=ms;t._paint_transport_cursor(painter,t._timeline_palette());painter.end()
            return surface.toImage().copy(round((t._time_to_x(a)-5)*dpr),round((t.RULER_HEIGHT+12)*dpr),20,60)
        assert strip(a)!=strip(a+16), 'the visible line must not wait for a whole logical pixel'
    finally:t._thumbnails.close();t._thumbnails.thread.join(2);t.close()


def test_follow_does_not_wait_for_a_whole_pixel_in_a_wide_viewport():
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    t=WaveformTimeline();t.resize(1400,200);t.set_project(SubtitleProject(StudioMedia('missing.mp4',duration_ms=3000000),
        cues=[StudioCue('a',0,3000000,'字幕')]))
    try:
        t.set_visible_window(7500,150000)
        assert t.follow_playing_playhead(60016)
        assert t.visible_start_ms==7516
    finally:t._thumbnails.close();t._thumbnails.thread.join(2);t.close()


def test_placeholder_raster_cannot_hide_a_new_decoded_frame(tmp_path,monkeypatch):
    cache=FilmstripCache(cache_root=tmp_path/'filmstrip');cache.set_paused(True)
    current=[None]
    monkeypatch.setattr(cache,'get',lambda *_a,**_k:current[0])
    def paint():
        surface=QPixmap(160,40);surface.fill(Qt.black);painter=QPainter(surface)
        cache.paint(painter,QRectF(0,0,160,40),'source',0,160,0,2000);painter.end()
        return surface.toImage()
    try:
        missing=paint()
        pixmap=QPixmap(128,72);pixmap.fill(QColor('green'));current[0]=pixmap
        decoded=paint()
        assert decoded!=missing
        assert decoded.pixelColor(20,20).green()>80
        cache._cell_rasters.clear();cache._cell_raster_bytes=0
        assert paint()==decoded
    finally:cache.close();cache.thread.join(2)
