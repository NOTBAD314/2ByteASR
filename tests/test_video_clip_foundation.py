"""Media presence and boundaries belong to clips, never to thumbnail readiness."""
import copy
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QRectF,Qt
from PySide6.QtGui import QColor,QImage,QPainter,QPixmap
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_video_track import paint_video_track
from twobyteasr.design.timeline_theme import timeline_palette
from twobyteasr.timeline.studio_edit_sequence import EditSequence,VideoSegment

APP=QApplication.instance() or QApplication([])


@pytest.mark.parametrize('state',['absent','loading','partial','failed','invalidated'])
@pytest.mark.parametrize('selected',[False,True])
def test_clip_foundation_and_true_tail_survive_every_thumbnail_state(state,selected):
    palette=timeline_palette('grape')
    sequence=EditSequence(source_path='source.mp4',source_duration_ms=10000,
        segments=[VideoSegment('clip','source.mp4',2000,7000,3000,8000)])
    class Thumbnails:
        def paint(self,painter,*_args):
            if state=='partial':
                # Even a decoded tile that extends beyond the whole clip is
                # clipped by the owner before the selected outline is redrawn.
                painter.fillRect(QRectF(360,0,400,80),QColor('red'))
    image=QImage(800,80,QImage.Format_ARGB32);image.fill(QColor(palette.background))
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
    paint_video_track(painter,sequence,palette,QRectF(0,0,800,70),200,800,
        lambda ms:200+ms*.05,'clip' if selected else '',
        None if state=='absent' else Thumbnails(),False)
    painter.end()
    # True clip interval is x350..600, regardless of thumbnail state.
    background=QColor(palette.background)
    assert image.pixelColor(355,35)!=background
    assert image.pixelColor(348,35)==background
    assert image.pixelColor(604,35)==background
    assert image.pixelColor(790,35)==background
    # A visible start/end and a base colour even with zero decoded pixels.
    if state!='partial':assert image.pixelColor(450,48)!=background
    if selected:
        edge=image.pixelColor(350,35);expected=QColor(palette.clip_selected_border)
        assert abs(edge.red()-expected.red())<30


def test_project_switch_rejects_queued_image_before_the_next_paint(tmp_path):
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.studio.video_filmstrip import FilmstripView
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    timeline=WaveformTimeline();cache=timeline._thumbnails;cache.set_paused(True)
    a=SubtitleProject(StudioMedia('a.mp4',duration_ms=10000));b=copy.deepcopy(a)
    timeline.set_project(a)
    cache.set_view((FilmstripView('a.mp4',(0,),owner='old-project'),))
    generation=cache.generation;key=next(iter(cache.wanted))
    timeline.set_project(b)
    image=QImage(16,9,QImage.Format_RGB32);image.fill(QColor('red'))
    cache._accept(key,image,generation)
    try:
        assert cache.generation>generation and key not in cache.memory
        assert not cache.wanted
    finally:cache.close();cache.thread.join(2);timeline.close()
