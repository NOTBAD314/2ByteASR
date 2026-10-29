import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMovie
from PySide6.QtTest import QTest
from PIL import Image
from twobyteasr.caption_design.candidate_preview_player import CandidatePreviewPlayer

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

def test_png_playback_retains_alpha_crop_and_real_media_time(app,tmp_path):
    for i in range(24):
        im=Image.new('RGBA',(40,20));im.paste((i*10,90,30,255),(10,5,30,15));im.save(tmp_path/f'{i:04}.png')
    motion=dict(transparent_frames=str(tmp_path),fps=24,frame_count=24,duration_ms=1000,subject_bbox=[8,3,32,17])
    player=CandidatePreviewPlayer(motion)
    player.jumpToFrame(12)
    pix=player.currentPixmap().toImage()
    assert (pix.width(),pix.height())==(24,14) and pix.pixelColor(0,0).alpha()==0
    assert pix.pixelColor(3,3).red()==120
    for i in range(24):player.jumpToFrame(i);player.currentPixmap()
    assert len(player.cache)<=12
    player.jumpToFrame(0);player.start();QTest.qWait(420);player.setPaused(True)
    assert 8<=player.currentFrameNumber()<=13
    paused=player.currentFrameNumber();QTest.qWait(70);assert player.currentFrameNumber()==paused
    player.setSpeed(50);player.setPaused(False);QTest.qWait(210);player.setPaused(True)
    assert 1<=player.currentFrameNumber()-paused<=4
    player.stop();assert player.state()==QMovie.NotRunning
    context=CandidatePreviewPlayer(motion,context=True)
    assert context.currentPixmap().size().width()==40

def test_enlarged_preview_uses_the_same_png_sequence(app,tmp_path):
    from twobyteasr.caption_design.theme_concept_dialog import MotionPreviewDialog
    Image.new('RGBA',(40,20),(255,255,255,0)).save(tmp_path/'0000.png')
    motion=dict(transparent_frames=str(tmp_path),fps=24,frame_count=1,duration_ms=1000,subject_bbox=[8,3,32,17],context={})
    dialog=MotionPreviewDialog(dict(name='透明放大',motion_preview=motion),None)
    assert isinstance(dialog.movie,CandidatePreviewPlayer)
    dialog.close()
