"""User-visible drag contracts, independent of Windows input injection tests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QEvent, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtTest import QTest

from twobyteasr.app import window_constraints as wc
from twobyteasr.app.window_chrome_widgets import WindowTitleBar


@pytest.fixture
def chrome(monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = QWidget(None,Qt.Window|Qt.FramelessWindowHint)
    bar = WindowTitleBar(w)
    layout = QVBoxLayout(w)
    layout.addWidget(bar)
    layout.addStretch()
    w.resize(500,400)
    w.show()
    b = wc.install_window_bounds(w)
    QTest.qWait(25)
    state = {'pos':w.mapToGlobal(QPoint(150,20)), 'buttons':Qt.LeftButton}
    monkeypatch.setattr(QCursor,'pos',staticmethod(lambda:QPoint(state['pos'])))
    monkeypatch.setattr(QGuiApplication,'mouseButtons',staticmethod(lambda:state['buttons']))
    monkeypatch.setattr(wc,'_start_system_move',lambda window:False,raising=False)
    yield w,bar,b,state
    drag = getattr(w,'_title_drag',None)
    if drag is not None:
        drag.stop('test-end')
    w.close()
    w.deleteLater()
    app.processEvents()


def begin(w,bar,state):
    state['pos'] = bar.mapToGlobal(QPoint(150,15))
    QTest.mousePress(bar,Qt.LeftButton,Qt.NoModifier,QPoint(150,15))
    return getattr(w,'_title_drag',None)


def test_normal_title_press_enters_the_same_protected_path(chrome):
    w,bar,b,state = chrome
    begin(w,bar,state)
    assert wc.in_move_size_loop(w)


def test_native_caption_hit_uses_title_space_and_excludes_all_buttons(chrome):
    from twobyteasr.app.window_native_frame import caption_target
    w,bar,b,state=chrome
    w.window_title_bar=bar
    assert caption_target(w,bar.mapTo(w,QPoint(20,15)))=='windowTitleBar'
    for button in (bar.minimize_button,bar.maximize_button,bar.close_button):
        assert caption_target(w,button.mapTo(w,button.rect().center())) is None


def test_tall_window_follows_mouse_and_keeps_partial_bottom_after_release(chrome):
    w,bar,b,state = chrome
    area=w.screen().availableGeometry()
    w.setGeometry(area.x()+30,area.y()+10,500,area.height()-24)
    QTest.qWait(30)
    drag=begin(w,bar,state)
    start=w.pos()
    press=QPoint(state['pos'])
    for dy in (30,80,160,130):
        state['pos']=press+QPoint(0,dy)
        drag.poll()
        QTest.qWait(10)
        assert w.y()==start.y()+dy
    state['buttons']=Qt.NoButton
    drag.poll()
    QTest.qWait(400)
    assert w.y()==start.y()+130
    assert w.frameGeometry().bottom()>area.bottom()


def test_click_on_an_already_user_placed_window_keeps_its_position(chrome):
    w,bar,b,state=chrome
    b.begin_interaction('manual')
    w.move(40,w.screen().availableGeometry().bottom()-100)
    b.end_interaction('release')
    QTest.qWait(30)
    point=w.pos()
    drag=begin(w,bar,state)
    state['buttons']=Qt.NoButton
    drag.poll()
    QTest.qWait(60)
    assert w.pos()==point


def test_maximized_click_does_not_restore_and_threshold_restores_once(chrome,monkeypatch):
    w,bar,b,state=chrome
    w.showMaximized()
    QTest.qWait(20)
    calls=[]
    original=w.showNormal
    monkeypatch.setattr(w,'showNormal',lambda:(calls.append(1),original()))
    drag=begin(w,bar,state)
    drag.poll()
    assert w.isMaximized() and calls==[]
    press=QPoint(state['pos'])
    for dy in (1,QApplication.startDragDistance()+5,50,70):
        state['pos']=press+QPoint(0,dy)
        drag.poll()
    assert calls==[1] and not w.isMaximized()
    assert w.frameGeometry().contains(state['pos'])


def test_reentrant_system_handoff_cannot_restore_or_move_twice(chrome,monkeypatch):
    w,bar,b,state=chrome
    w.showMaximized()
    QTest.qWait(20)
    drag=begin(w,bar,state)
    calls=[]
    def native(window):
        calls.append(window.geometry())
        drag.poll()  # Windows can run nested Qt timers inside startSystemMove
        return True
    monkeypatch.setattr(wc,'_start_system_move',native)
    state['pos']+=QPoint(0,80)
    drag.poll()
    final=w.geometry()
    for _ in range(3):
        state['pos']+=QPoint(10,10)
        drag.poll()
    assert len(calls)==1 and w.geometry()==final
    assert b.owner=='native-pending' and not drag.timer.isActive()


def test_fullscreen_title_input_does_not_move_or_restore(chrome,monkeypatch):
    w,bar,b,state=chrome
    w.showFullScreen()
    QTest.qWait(25)
    before=w.geometry()
    calls=[]
    original=w.move
    monkeypatch.setattr(w,'move',lambda *args:(calls.append(args),original(*args)))
    begin(w,bar,state)
    QTest.mouseMove(bar,QPoint(150,130))
    QTest.mouseRelease(bar,Qt.LeftButton)
    QTest.qWait(400)
    assert w.isFullScreen() and w.geometry()==before
    assert calls==[]
    assert getattr(w,'_title_drag',None) is None


def test_explicit_fullscreen_exit_keeps_the_existing_maximize_control(chrome):
    w,bar,b,state=chrome
    w.showFullScreen()
    QTest.qWait(25)
    bar.maximize_button.click()
    assert not w.isFullScreen() and w.isMaximized()


def test_escape_manual_drag_restores_start_and_releases_ownership(chrome):
    w,bar,b,state=chrome
    before=w.geometry()
    drag=begin(w,bar,state)
    state['pos']+=QPoint(0,80)
    drag.poll()
    QApplication.sendEvent(bar,QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
    QTest.qWait(40)
    assert w.geometry()==before and b.owner=='idle'
    assert getattr(w,'_title_drag',None) is None


@pytest.mark.parametrize('kind',[QEvent.WindowDeactivate,QEvent.Hide,QEvent.Close])
def test_lifecycle_cancels_drag_and_queued_restore(chrome,kind):
    w,bar,b,state=chrome
    old=[]
    b._queue('return-screen',15,lambda:old.append(1))
    begin(w,bar,state)
    QApplication.sendEvent(w,QEvent(kind))
    state['pos']+=QPoint(0,200)
    QTest.qWait(70)
    assert not old and b.owner=='idle' and getattr(w,'_title_drag',None) is None


def test_capture_loss_cleans_manual_fallback(chrome):
    w,bar,b,state=chrome
    drag=begin(w,bar,state)
    state['pos']+=QPoint(0,80)
    drag.poll()
    QApplication.sendEvent(bar,QEvent(QEvent.UngrabMouse))
    assert b.owner=='idle' and getattr(w,'_title_drag',None) is None


@pytest.mark.parametrize('change',['press','state','screen','dpi','hide'])
def test_old_callbacks_cannot_act_after_new_user_or_display_intent(chrome,change):
    w,bar,b,state=chrome
    calls=[]
    b._queue('return-screen',20,lambda:calls.append('old-restore'))
    b._queue('repair',20,lambda:calls.append('old-repair'))
    if change=='press':
        begin(w,bar,state)
    elif change=='state':
        w.showMaximized()
    elif change=='screen':
        b._screen_changed()
    elif change=='dpi':
        b.native_message(0x02E0,144|(144<<16),0)
    else:
        w.hide()
    QTest.qWait(65)
    assert calls==[]


def test_broken_maximized_repair_cannot_run_in_a_gesture(chrome,monkeypatch):
    w,bar,b,state=chrome
    monkeypatch.setattr(wc,'special_geometry_broken',lambda w:True)
    calls=[]
    monkeypatch.setattr(wc,'place_on_screen',lambda *args:calls.append(args))
    begin(w,bar,state)
    b._repair_if_broken()
    assert not calls


def test_old_minimize_screen_return_cannot_undo_a_later_drag(chrome,monkeypatch):
    w,bar,b,state=chrome
    from types import SimpleNamespace
    target=SimpleNamespace(availableGeometry=lambda:QRect(-1000,0,900,800))
    screens=QApplication.screens()
    monkeypatch.setattr(QApplication,'screens',staticmethod(lambda:screens+[target]))
    calls=[]
    monkeypatch.setattr(wc,'place_on_screen',lambda *args:calls.append(args))
    callback=lambda:b._return_to_screen(target,Qt.WindowMaximized)
    if hasattr(b,'_queue'):
        b._queue('return-screen',30,callback)
    else:  # Replay exactly the former unversioned singleShot contract.
        QTimer.singleShot(30,callback)
    begin(w,bar,state)
    QTest.mouseRelease(bar,Qt.LeftButton)
    state['buttons']=Qt.NoButton
    QTest.qWait(80)
    assert not calls


def test_user_title_recovery_only_translates_and_converges(chrome):
    w,bar,b,state=chrome
    w.resize(900,1200)
    w.move(-5000,-4000)
    before=w.size()
    wc.constrain(w,user_placed=True)
    first=w.geometry()
    wc.constrain(w,user_placed=True)
    assert w.size()==before and w.geometry()==first
    assert wc.title_reachable(w.frameGeometry())


def test_negative_screen_recovery_chooses_smallest_translation():
    screens=[QRect(0,0,1920,1040),QRect(-1440,-521,1152,2712)]
    frame=QRect(-1000,-700,900,1300)
    recovered=wc.recover_title_rect(frame,screens)
    assert recovered.x()==-1000 and recovered.y()==-513
    assert recovered.size()==frame.size()


def test_saved_normal_geometry_is_not_replaced_by_a_maximized_frame(chrome):
    w,bar,b,state=chrome
    expected=w.geometry()
    wc.remember_normal_geometry(w)
    w.showMaximized()
    wc.remember_normal_geometry(w)
    assert wc.normal_restore_geometry(w)==expected
    wc.restore_normal_window(w)
    assert w.geometry()==expected


def test_dialog_bounds_stay_strict_when_user_places_it(chrome):
    w,bar,b,state=chrome
    child=QWidget(w,Qt.Dialog)
    child.resize(400,300)
    child.show()
    child.move(w.x()+200,w.y()+300)
    wc.constrain(child,within_parent=True,user_placed=True)
    assert wc.available_rect(child,within_parent=True).contains(child.frameGeometry())
    child.close()


def test_top_level_dialog_keeps_full_screen_bounds_even_without_a_parent(chrome):
    from PySide6.QtWidgets import QDialog
    w,bar,b,state=chrome
    dialog=QDialog()
    dialog.resize(400,300)
    dialog.show()
    area=dialog.screen().availableGeometry()
    dialog.move(area.x()+20,area.bottom()-80)
    wc.constrain(dialog,user_placed=True)
    assert wc.available_rect(dialog).contains(dialog.frameGeometry())
    dialog.close()


def test_keyboard_native_move_without_mouse_gets_a_release_checkpoint(chrome):
    w,bar,b,state=chrome
    state['buttons']=Qt.NoButton
    b.native_message(0x0231)
    w.move(30,w.screen().availableGeometry().bottom()-100)
    b.native_message(0x0232)
    point=w.pos()
    QTest.qWait(80)
    assert b.owner=='idle' and w.pos()==point


def test_restore_finishes_native_maximization_without_losing_normal_size(chrome,monkeypatch):
    from types import SimpleNamespace
    w,bar,b,state=chrome
    original=w.geometry()
    w.showMaximized()
    QTest.qWait(20)
    flags={'zoomed':True,'calls':[]}
    monkeypatch.setattr(wc,'native_frame',lambda widget:dict(zoomed=flags['zoomed'],iconic=False,rect=(0,0,1,1)))
    def show(hwnd,command):
        flags['calls'].append(command)
        flags['zoomed']=False
    monkeypatch.setattr(wc,'_user32',lambda:SimpleNamespace(ShowWindow=show))
    wc.restore_normal_window(w)
    assert flags['calls']==[9] and not w.isMaximized()
    assert w.geometry()==original


def test_maximize_completes_native_state_once_and_preserves_restore_size(chrome,monkeypatch):
    from types import SimpleNamespace
    w,bar,b,state=chrome
    original=w.geometry()
    native={'zoomed':False}
    commands=[]
    monkeypatch.setattr(wc,'native_frame',lambda widget:dict(zoomed=native['zoomed'],iconic=False,
        rect=(widget.x(),widget.y(),widget.x()+widget.width(),widget.y()+widget.height())))
    def show(hwnd,command):
        commands.append(command)
        native['zoomed']=True
    monkeypatch.setattr(wc,'_user32',lambda:SimpleNamespace(ShowWindow=show))
    wc.maximize_window(w)
    wc.maximize_window(w)
    assert w.isMaximized() and native['zoomed'] and commands==[3]
    assert w.normalGeometry()==original


@pytest.mark.parametrize('action',['escape','deactivate','capture','fullscreen'])
def test_manual_resize_ends_on_cancellation(chrome,action):
    w,bar,b,state=chrome
    original=w.geometry()
    b.begin_interaction('manual-resize')
    w._resize_dragging=True
    w._resize_start_geom=QRect(original)
    w._resize_start_pos=QPoint(0,0)
    w._resize_edge='br'
    w.resize(w.width()+40,w.height()+30)
    if action=='escape':
        QApplication.sendEvent(bar,QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
        assert w.geometry()==original
    elif action=='fullscreen':
        w.showFullScreen()
    else:
        QApplication.sendEvent(w,QEvent(QEvent.WindowDeactivate if action=='deactivate' else QEvent.UngrabMouse))
    assert b.owner=='idle' and not w._resize_dragging
