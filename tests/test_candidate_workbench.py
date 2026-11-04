import json,time,copy,threading
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication,QWidget,QPushButton,QLabel
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog,FittedPicture
from twobyteasr.caption_design.studio_theme_draft import StudioThemeDraftController

@pytest.fixture(scope='module')
def app():
    value=QApplication.instance() or QApplication([])
    yield value

def failed():return dict(id='A',name='RIG导航全息铭牌',composition='原始设计保留',technical_status='failed',technical_errors=[dict(category='motion_structure',actual='transformOrigin at track level')])

def test_unique_preview_fixed_footer_and_candidate_selection_survive_updates(app):
    concepts=[failed(),dict(id='B',name='生成中的方向',pending=True),dict(id='C',name='完整稿',authored_theme={'cueHtml':'source'},motion_preview={'status':'motion_ready'},preview_integrity_verified=True)]
    dialog=ThemeConceptDialog(concepts,{})
    dialog.show();app.processEvents()
    assert len(dialog.findChildren(FittedPicture))==1 and dialog.candidate_list.count()==3
    dialog.candidate_list.setCurrentRow(2);assert dialog.primary.text()=='采用这个方向'
    dialog.update_concepts(copy.deepcopy(concepts),{})
    assert dialog.current_concept()['id']=='C'
    for width,height in [(1120,760),(820,620),(660,500)]:
        dialog.resize(width,height);app.processEvents()
        assert dialog.rect().contains(dialog.primary.geometry()),(width,height,dialog.primary.geometry())
        assert dialog.primary.isVisible() and dialog.picture.width()>100
    dialog.candidate_list.setCurrentRow(0)
    signals=[];dialog.recovery_requested.connect(lambda *args:signals.append(args))
    QTest.mouseClick(dialog.primary,Qt.LeftButton)
    assert signals==[('A','continue')] and '建立任务' in dialog.action_feedback.text()
    dialog.close()

def test_controller_rejection_is_immediate_durable_and_never_silent(app,tmp_path):
    page=QWidget();page._show_studio_hint=lambda text:None
    controller=StudioThemeDraftController(page);controller.root=tmp_path
    controller.current=SimpleNamespace(request_id='job');controller.design={'concepts':[failed()]}
    dialog=ThemeConceptDialog(controller.design['concepts'],{},page);controller._concept_dialog=dialog
    dialog.recovery_requested.connect(lambda key,mode:controller.retry_technical_candidate(key,recovery_mode=mode))
    controller.generation_running=True
    started=time.perf_counter();QTest.mouseClick(dialog.primary,Qt.LeftButton);elapsed=time.perf_counter()-started
    assert elapsed<.2 and '未重复发送' in dialog.action_feedback.text()
    receipt=json.loads(next((tmp_path/'candidate-actions').glob('*.json')).read_text('utf8'))
    assert receipt['status']=='rejected' and receipt['candidate_id']=='A'
    controller.generation_running=False;controller.phase='CHOOSING';controller._target_current=lambda:False
    controller.retry_technical_candidate('A')
    assert '字幕或工程对象已改变' in dialog.action_feedback.text()
    dialog.close();page.close()

def test_primary_adopt_needs_verified_exact_version(app):
    c=failed();dialog=ThemeConceptDialog([c],{})
    dialog.choose('A');assert not dialog.selected_id
    c.update(authored_theme={'cueHtml':'exact'},technical_status='passed',motion_preview={'status':'motion_ready'},preview_integrity_verified=True)
    dialog.update_concepts([c],{});dialog.choose('A')
    from twobyteasr.caption_design.candidate_attempt import revision
    assert dialog.selected_id=='A' and dialog.selected_revision==revision(c)


def test_exit_segment_uses_coalesced_gif_timestamps(app,tmp_path):
    from PIL import Image
    from twobyteasr.caption_design.theme_concept_dialog import movie_frame_times
    path=tmp_path/'variable.gif'
    frames=[Image.new('RGB',(30,20),color) for color in ('red','green','blue')]
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=[100,5000,100],loop=0)
    assert movie_frame_times(path)==[0,100,5100]
    c=dict(id='A',name='时序测试',authored_theme={'motionSpec':{'buildMs':100,'resolveMs':100}},
        motion_preview={'status':'motion_ready','gif':str(path),'duration_ms':5200},preview_integrity_verified=True)
    dialog=ThemeConceptDialog([c],{})
    dialog.segment.setCurrentIndex(2)
    assert dialog.movie.currentFrameNumber()==2
    dialog.close()


def test_invalid_saved_source_recovery_explains_rejection(app,tmp_path):
    page=QWidget();messages=[];page._show_studio_hint=messages.append
    controller=StudioThemeDraftController(page);controller.root=tmp_path
    c=failed();c.update(authored_theme={'broken':True},preview_integrity_error='preview missing')
    controller.current=SimpleNamespace(request_id='job');controller.design={'concepts':[c]}
    controller.phase='CHOOSING';controller._target_current=lambda:True
    assert controller.retry_technical_candidate('A') is False
    assert '源码尚未通过检查' in messages[-1]
    assert json.loads(next((tmp_path/'candidate-actions').glob('*.json')).read_text('utf8'))['status']=='rejected'
    page.close()
