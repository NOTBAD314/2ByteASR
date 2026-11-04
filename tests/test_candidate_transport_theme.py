import copy
import pytest
from PIL import Image
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMovie, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def candidate(tmp_path, png=True):
    frames=[]
    for i in range(12):
        im=Image.new('RGBA',(80,40),(i*20,90,80,255))
        im.save(tmp_path/f'{i:04}.png');frames.append(im.convert('RGB'))
    gif=tmp_path/'movie.gif'
    frames[0].save(gif,save_all=True,append_images=frames[1:],duration=40,loop=1)
    motion=dict(status='motion_ready',gif=str(gif),fps=24,frame_count=12,duration_ms=500)
    if png:motion['transparent_frames']=str(tmp_path)
    return dict(id='A',name='主题示例',composition='可读的主题说明',preview_integrity_verified=True,
        motion_preview=motion,authored_theme={'motionSpec':{'buildMs':125,'resolveMs':125}})


@pytest.mark.parametrize('png',[True,False])
def test_autoplay_loop_click_seek_drag_and_keyboard(app,tmp_path,png):
    c=candidate(tmp_path,png);d=ThemeConceptDialog([c],{});d.show();QTest.qWait(80)
    assert d.movie.state()==QMovie.Running and not d.play_button.text()
    frames=[];d.movie.frameChanged.connect(frames.append)
    QTest.qWait(1800)
    assert sum(b<a for a,b in zip(frames,frames[1:]))>=2
    QTest.mouseClick(d.picture,Qt.LeftButton)
    assert d.movie.state()==QMovie.Paused and d.play_button.accessibleName()=='播放'
    QTest.mouseClick(d.picture,Qt.LeftButton)
    assert d.movie.state()==QMovie.Running
    slider=d.scrubber
    QTest.mouseClick(slider,Qt.LeftButton,pos=QPoint(round(slider.width()*.75),slider.height()//2))
    assert d.movie.state()==QMovie.Paused and 7<=d.movie.currentFrameNumber()<=9
    QTest.mousePress(slider,Qt.LeftButton,pos=QPoint(slider.width()//2,slider.height()//2))
    QTest.mouseMove(slider,QPoint(1,slider.height()//2))
    QTest.mouseRelease(slider,Qt.LeftButton,pos=QPoint(1,slider.height()//2))
    assert d.movie.currentFrameNumber()==0
    QTest.keyClick(slider,Qt.Key_End)
    assert d.movie.currentFrameNumber()==11
    d.update_concepts(copy.deepcopy([c]),{})
    assert d.movie.state()==QMovie.Paused  # background task refresh must not resume manual inspection
    QTest.mouseClick(d.play_button,Qt.LeftButton);assert d.movie.state()==QMovie.Running
    d.close();assert d.movie.state()==QMovie.NotRunning


def test_live_theme_and_pending_to_ready(app,tmp_path,monkeypatch):
    from twobyteasr.design.ui_theme import THEMES
    import twobyteasr.design.theme_manager as tm
    d=ThemeConceptDialog([dict(id='A',name='处理中',pending=True)],{});d.show()
    assert not d.play_button.isEnabled()
    for key,t in THEMES.items():
        monkeypatch.setattr(tm,'theme_key',lambda key=key:key)
        d.refresh_theme_palette();app.processEvents()
        assert d.title.palette().color(QPalette.WindowText).name().lower()==t.text.lower()
        assert d.details['设计说明'].palette().color(QPalette.Text).name().lower()==t.text_secondary.lower()
    d.update_concepts([candidate(tmp_path)],{})
    assert d.play_button.isEnabled() and d.movie.state()==QMovie.Running
    d.segment.setCurrentIndex(1);QTest.qWait(300)
    assert d.movie.currentFrameNumber()<=4
    d.segment.setCurrentIndex(2);QTest.qWait(300)
    assert d.movie.currentFrameNumber()>=8
    d.close()
