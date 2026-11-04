from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.studio.studio_timeline import WaveformTimeline

APP = QApplication.instance() or QApplication([])


def make_timeline():
    timeline=WaveformTimeline()
    timeline.resize(1000,360)
    project=SubtitleProject(media=StudioMedia('diagnostic.mp4',duration_ms=30000),
        speakers=[StudioSpeaker('s')],cues=[StudioCue('a',1000,3000,'字幕','s')])
    timeline.set_project(project); timeline.show(); APP.processEvents()
    return timeline


def test_cursor_is_async_mouse_transparent_and_does_not_rebuild_base():
    timeline=make_timeline()
    try:
        layer=timeline._transport_overlay
        assert layer.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert layer.focusPolicy()==Qt.FocusPolicy.NoFocus
        cached=timeline._static_timeline_cache
        paints=[]; original=timeline._paint_transport_cursor
        timeline._paint_transport_cursor=lambda *args:(paints.append(timeline.playhead_ms),original(*args))[-1]
        timeline.set_playhead(2500)
        assert paints==[]  # update is queued, never synchronous repaint.
        APP.processEvents()
        assert 2500 in paints
        assert timeline._static_timeline_cache is cached
        assert not timeline._static_timeline_dirty
        assert timeline._transport_cursor_region(2500).boundingRect().height()<=timeline.height()
    finally: timeline.close()


def test_old_cursor_pixels_clear_and_resize_tracks_parent():
    timeline=make_timeline()
    try:
        timeline.set_playhead(1500); APP.processEvents()
        first=timeline.grab().toImage()
        old_x=round(timeline._time_to_x(1500))
        sample_y=timeline._canvas_bottom()-8
        first_pixel=first.pixelColor(old_x,sample_y)
        timeline.set_playhead(8000); APP.processEvents()
        second=timeline.grab().toImage()
        assert second.pixelColor(old_x,sample_y) != first_pixel
        timeline.resize(720,300); APP.processEvents()
        assert timeline._transport_overlay.geometry()==timeline.rect()
        timeline.set_selected('a'); timeline.set_active_cues({'a'}); APP.processEvents()
        assert timeline.selected_id=='a'
        assert timeline.active_cue_ids==frozenset({'a'})
    finally: timeline.close()
