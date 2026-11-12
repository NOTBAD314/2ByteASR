"""Original gesture selection, decode, motion policy and movie retirement."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImageReader, QMovie
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from twobyteasr.app.home_tour import TourAnim, tutorial_anim_path
from twobyteasr.app.tour_motion import SCENES


@pytest.fixture
def animation():
    app=QApplication.instance() or QApplication([])
    app.setProperty('reduceMotion',False)
    view=TourAnim();view.show()
    yield app,view
    view.stop();view.close();view.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.setProperty('reduceMotion',None)


@pytest.mark.parametrize('light',[False,True])
def test_all_original_resources_win_over_program_scenes_and_decode(animation,light):
    app,view=animation
    assert b'webp' in [bytes(f) for f in QImageReader.supportedImageFormats()]
    root=tutorial_anim_path('drop',light).parent
    for path in root.glob('*-light.webp' if light else '*-dark.webp'):
        name=path.stem.rsplit('-',1)[0]
        assert view.load(name,light),path
        assert view.source=='original-webp' and view._scene is None,path
        movie=view._movie
        assert movie.frameCount()>1 and not movie.currentImage().isNull(),path
        initial=movie.currentImage().cacheKey()
        view.start();QTest.qWait(135)
        assert movie.state()==QMovie.MovieState.Running and movie.currentFrameNumber()>0,path
        assert movie.currentImage().cacheKey()!=initial,path
        assert movie.currentImage().width()>=800,path


@pytest.mark.parametrize('light',[False,True])
def test_reduced_motion_stills_and_new_step_fallback(animation,light):
    app,view=animation
    app.setProperty('reduceMotion',True)
    assert view.play('drop',light)
    assert view.source=='original-still' and view._movie is None and not view._still.isNull()
    assert not view._ticker.isActive()
    assert view.play('plan_compare',light)
    assert view.source=='program-scene' and not view._ticker.isActive()


def test_step_switch_and_hidden_or_closed_movie_has_no_late_frames(animation):
    app,view=animation
    assert view.play('edit',False)
    old=view._movie
    assert view.play('speakers',False)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not isValid(old)
    active=view._movie
    view.hide();QTest.qWait(90)
    assert active.state()!=QMovie.MovieState.Running
    view.show();view.start();QTest.qWait(80)
    assert active.state()==QMovie.MovieState.Running
    view.stop();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not isValid(active) and not view._ticker.isActive()
    assert not view.load('resource-does-not-exist',False)


def test_renamed_language_step_uses_original_language_gesture(animation):
    _app,view=animation
    assert view.load('spoken',True)
    assert view.source=='original-webp' and view._movie.fileName().endswith('language-light.webp')


@pytest.mark.parametrize('language,backend,expected',[('zh','local','firered'),('ja','local','ctc'),
                                                     ('en','qwen_aligner','ctc'),('ja','off','timeline_mg')])
def test_current_timeline_step_selects_matching_original_or_off_demo(language,backend,expected):
    from types import SimpleNamespace
    from twobyteasr.app.home_tour import tutorial_steps
    noop=lambda *args,**kwargs:None
    window=SimpleNamespace(_tutorial_prepare_demo=noop,_tutorial_add_demo_media=noop,
        _tutorial_demo_completion=noop,_open_api_key_explainer=noop,
        _subtitle_language_options=lambda:dict(recognition_language=language),
        legacy=SimpleNamespace(RUNTIME_SETTINGS=dict(models=dict(firered_asr_backend=backend))))
    selections=[step.anim for step in tutorial_steps(window) if callable(step.anim)]
    assert len(selections)==1 and selections[0]()==expected


def test_missing_or_bad_webp_uses_declared_fallback_only(animation,monkeypatch,tmp_path):
    from twobyteasr.app import home_tour
    _app,view=animation
    bad=tmp_path/'drop-dark.webp';bad.write_bytes(b'broken')
    monkeypatch.setattr(home_tour,'tutorial_anim_path',lambda *args,**kw:bad)
    assert view.load('drop',False) and view.source=='program-scene'
    assert view.resource_error==bad.name
    assert not view.load('missing-new-step',False)
