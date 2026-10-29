"""Fail-closed cover evidence, input ownership and ordered retirement contracts."""
from contextlib import contextmanager
import os
from types import SimpleNamespace as NS
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from twobyteasr.design import native_loading_cover as cover
from twobyteasr.studio.studio_loading import StudioLoadingSession, StudioLoadingView

APP = QApplication.instance() or QApplication([])


class Surface(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.blocks = {}

    def set_presentation_blocked(self, reason, value):
        self.blocks[reason] = bool(value)


@pytest.fixture
def native_session(monkeypatch):
    # Session semantics only. Actual Windows styles/ULW are a separate private
    # acceptance tier; these offscreen tests do not certify native presentation.
    monkeypatch.setattr(cover, 'native_cover_supported', lambda owner:True)
    evidence = {'valid':True}
    def state(view):
        valid = evidence['valid'] and view.isVisible()
        return dict(requested=True, supported=True, verified=valid,
                    reasons=[] if valid else ['cover not verified'])
    monkeypatch.setattr(StudioLoadingView, 'native_cover_state', state)
    owner = QWidget();owner.resize(900,700)
    pages = QStackedWidget(owner);pages.setGeometry(owner.rect());pages.addWidget(QWidget())
    owner.show();APP.processEvents()
    session = StudioLoadingSession(pages, owner, page_stack=True, native_cover=True, input_host=pages)
    own_video = Surface(pages)
    other_owner = QWidget();other_video = Surface(other_owner)
    session._surfaces = [weakref.ref(own_video), weakref.ref(other_video)]
    yield NS(owner=owner,pages=pages,session=session,evidence=evidence,video=own_video,other=other_video)
    session.on_present = session.on_retired = session.on_reveal = None
    session.abort()
    owner.close();other_owner.close();owner.deleteLater();other_owner.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_verified_cover_is_painted_and_input_protected_before_showing_editor(native_session):
    env=native_session;session=env.session;calls=[]
    session.on_present=lambda:calls.append((session.view.isVisible(),env.pages.isEnabled(),
                                          session.native_cover_state()['verified']))
    session.begin('A')
    assert calls==[(True,False,True)]
    assert session.native_cover_requested and session.uses_native_cover
    assert session.view.parentWidget() is env.owner and not session.view.isWindow()
    assert not session.view.page_stack and env.pages.indexOf(session.view)==-1
    assert session.view.geometry()==env.owner.rect()
    assert env.video.blocks['loading'] is False
    assert env.other.blocks['loading'] is True


def test_unverified_cover_defers_callback_and_preserves_existing_surface_ownership(native_session):
    env=native_session;session=env.session;calls=[]
    env.video.blocks['loading']=False;env.other.blocks['loading']=True
    env.evidence['valid']=False;session.on_present=lambda:calls.append(session.generation)
    generation=session.begin('A',present=False)
    assert session.present() is False and not calls
    assert session.native_cover_state()['status']=='pending'
    assert env.video.blocks['loading'] is False and env.other.blocks['loading'] is True
    env.evidence['valid']=True
    session._native_cover_updated()
    session._native_cover_updated()
    assert calls==[generation]
    assert not env.video.blocks['loading'] and env.other.blocks['loading']


def test_warm_entry_does_not_blank_old_video_before_cover_has_authority(native_session):
    env=native_session;session=env.session;calls=[]
    env.video.blocks.update(loading=False,navigation=False)
    env.other.blocks.update(loading=False,navigation=True)
    before=(dict(env.video.blocks),dict(env.other.blocks))
    env.evidence['valid']=False
    session.on_present=lambda:calls.append((session.view.isVisible(),env.pages.isEnabled()))
    session.begin('new-project',present=False)
    assert (env.video.blocks,env.other.blocks)==before  # apply_theme/initial invalidation
    assert session.present() is False
    assert (env.video.blocks,env.other.blocks)==before and not calls
    env.evidence['valid']=True;session._native_cover_updated()
    assert calls==[(True,False)]
    assert env.video.blocks==dict(loading=False,navigation=False)
    assert env.other.blocks==dict(loading=True,navigation=True)


def test_losing_cover_verification_blocks_native_video_again(native_session):
    env=native_session;session=env.session;session.begin('A')
    assert not env.video.blocks['loading']
    env.evidence['valid']=False;session._native_cover_updated()
    assert env.video.blocks['loading'] and not env.pages.isEnabled()
    env.evidence['valid']=True;session._native_cover_updated()
    assert not env.video.blocks['loading']


def test_unverified_pending_cover_terminates_with_a_visible_failure(native_session):
    env=native_session;session=env.session;called=[]
    env.evidence['valid']=False;session.on_present=lambda:called.append(True)
    generation=session.begin('A');token=session._native_pending_token
    session._native_cover_timeout(token,generation)
    assert session.state=='failed' and session.native_cover_state()['status']=='failed'
    assert session.view.isVisible() and not called and session.deliveries==0
    assert env.video.blocks['loading']


def test_failure_blocks_surfaces_even_when_a_card_is_verified(native_session):
    env=native_session;session=env.session
    session.begin('A')
    assert not env.video.blocks['loading']
    session.fail('读取工程','controlled project failure')
    assert session.native_cover_state()['verified']
    assert env.video.blocks['loading'] and env.other.blocks['loading']


@pytest.mark.parametrize('new_generation',[True,False])
def test_old_watchdog_cannot_fail_a_new_present_request(native_session,new_generation):
    env=native_session;session=env.session;env.evidence['valid']=False
    generation=session.begin('A');old=session._native_pending_token
    session.begin('B') if new_generation else session.present()
    assert session._native_pending_token is not old
    session._native_cover_timeout(old,generation)
    assert session.active and not session._native_cover_fault


def test_verified_cover_does_not_wait_for_watchdog(native_session):
    env=native_session;session=env.session;calls=[]
    env.evidence['valid']=False;session.on_present=lambda:calls.append(True)
    generation=session.begin('A');token=session._native_pending_token
    env.evidence['valid']=True;session._native_cover_updated()
    assert calls==[True] and session.native_cover_state()['verified']
    session._native_cover_timeout(token,generation)
    assert session.active and not session._native_cover_fault


def test_minimized_pending_owner_resumes_bounded_verification_on_restore(native_session,monkeypatch):
    env=native_session;session=env.session;env.evidence['valid']=False
    generation=session.begin('A');token=session._native_pending_token
    monkeypatch.setattr(env.owner,'isMinimized',lambda:True)
    session._native_cover_timeout(token,generation)
    assert session.native_cover_state()['status']=='waiting_for_visible_owner'
    monkeypatch.setattr(env.owner,'isMinimized',lambda:False)
    session._native_cover_updated()
    assert session._native_pending_token is not token
    session._native_cover_timeout(session._native_pending_token,generation)
    assert session.native_cover_state()['status']=='failed'


@pytest.mark.parametrize('initially_enabled',[True,False])
def test_input_lease_preserves_original_setting_across_generations(native_session,initially_enabled):
    env=native_session;session=env.session;env.pages.setEnabled(initially_enabled)
    card=session.view.card
    session.begin('A');session.begin('B');session.fail('读取工程','fixture failure')
    assert not env.pages.isEnabled() and session.view.card is card
    session.begin('C');session.abort()
    assert env.pages.isEnabled() is initially_enabled
    assert not session._input_lease.held


def test_retire_releases_input_then_paints_destination_inside_native_scope(native_session):
    env=native_session;session=env.session;events=[];inside={'value':False}
    @contextmanager
    def handoff():
        inside['value']=True;events.append('hold-enter')
        try:yield
        finally:events.append('hold-exit');inside['value']=False
    session.handoff_scope=handoff
    session.on_reveal=lambda:events.append('reveal')
    session.on_retired=lambda:events.append(('retired',session.view.isVisible(),env.pages.isEnabled(),inside['value']))
    generation=session.begin('A')
    assert session.deliver(generation)
    assert events==['hold-enter','reveal',('retired',False,True,True),'hold-exit']
    assert session.native_cover_state()['status']=='inactive'


def test_reentrant_new_request_from_retired_callback_keeps_its_input_lease(native_session):
    env=native_session;session=env.session;old=session.begin('A')
    session.on_retired=lambda:session.begin('B')
    assert not session.deliver(old)
    assert session.path=='B' and session.active and session.view.isVisible()
    assert not env.pages.isEnabled()
    session.on_retired=None;session.abort()
    assert env.pages.isEnabled()


def test_abort_does_not_clear_retry_or_record_cancelled_for_reentrant_request(native_session):
    session = native_session.session
    session.begin('A')
    retry_b = lambda: None
    session.on_retired = lambda: session.begin('B', on_retry=retry_b)

    session.abort()

    assert session.path == 'B' and session.active and session.state == 'preparing'
    assert session.on_retry is retry_b
    assert not any(event['event'] == 'cancelled' for event in session.events)


def test_resume_returns_its_own_epoch_without_recording_resume_for_reentrant_request(native_session):
    session = native_session.session
    a = session.begin('A')
    retry_b = lambda: None
    session.on_retired = lambda: session.begin('B', on_retry=retry_b)

    resumed_epoch = session.resume_ready('A')

    assert resumed_epoch == a + 1
    assert session.generation == a + 2
    assert session.path == 'B' and session.active and session.state == 'preparing'
    assert session.on_retry is retry_b
    assert not any(event['event'] == 'resumed' for event in session.events)


@pytest.mark.parametrize('callback',['on_present','on_reveal','on_retired'])
def test_callback_failure_keeps_same_cover_and_blocks_without_recursing(native_session,callback):
    env=native_session;session=env.session;calls=[]
    def broken():calls.append(callback);raise RuntimeError('controlled paint failure')
    if callback=='on_present':
        session.on_present=broken
        with pytest.raises(RuntimeError,match='controlled paint failure'):session.begin('A')
    else:
        epoch=session.begin('A');setattr(session,callback,broken)
        with pytest.raises(RuntimeError,match='controlled paint failure'):session.deliver(epoch)
    assert calls==[callback]
    assert session.state=='failed' and session.view.isVisible()
    assert not env.pages.isEnabled() and env.video.blocks['loading']
    assert session.native_cover_state()['status']=='failed'
    assert session.deliveries==0


def test_reentrant_request_during_input_restore_is_not_overwritten(native_session,monkeypatch):
    env=native_session;session=env.session;retired=[]
    epoch=session.begin('A');session.on_retired=lambda:retired.append(session.path)
    original=env.pages.setEnabled;triggered={'value':False}
    def enabled(value):
        original(value)
        if value and not triggered['value']:
            triggered['value']=True
            session.begin('B')
    monkeypatch.setattr(env.pages,'setEnabled',enabled)
    assert not session.deliver(epoch)
    assert session.path=='B' and session.active and not retired
    assert session.native_cover_state()['verified'] and not env.pages.isEnabled()
    session.on_retired=None;session.abort()
    assert env.pages.isEnabled()


def test_invalid_input_host_fails_without_disabling_root_or_showing_editor(native_session):
    env=native_session;session=env.session;called=[]
    session._input_lease=cover.InputHostLease(env.owner)
    session.on_present=lambda:called.append(True)
    session.begin('A',present=False)
    assert session.present() is False
    assert session.native_cover_state()['status']=='failed' and not called
    assert env.owner.isEnabled() and env.video.blocks['loading']


def test_old_pending_callback_cannot_fail_a_reentrant_new_generation(native_session):
    env=native_session;session=env.session
    env.evidence['valid']=False;session.begin('A')
    def old_callback():
        session.on_present=None
        session.begin('B')
        raise RuntimeError('obsolete A callback')
    session.on_present=old_callback;env.evidence['valid']=True
    session._native_cover_updated()
    assert session.path=='B' and session.active
    assert not session._native_cover_fault and not env.pages.isEnabled()


def test_unsupported_request_keeps_stack_parent_and_does_not_disable_card_host(monkeypatch):
    monkeypatch.setattr(cover,'native_cover_supported',lambda owner:False)
    owner=QWidget();pages=QStackedWidget(owner);pages.addWidget(QWidget())
    session=StudioLoadingSession(pages,owner,page_stack=True,native_cover=True,input_host=pages)
    pages.addWidget(session.view);session.on_present=lambda:pages.setCurrentWidget(session.view)
    owner.show();session.begin('A')
    assert session.native_cover_requested and not session.uses_native_cover
    assert session.view.parentWidget() is pages and session.view.page_stack
    assert pages.isEnabled() and session.view.isEnabled() and not session._input_lease.held
    owner.close();owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_cover_chrome_targets_root_window_and_reuses_drag_behavior(native_session,monkeypatch):
    env=native_session;bar=env.session.view.window_title_bar;calls=[]
    from twobyteasr.app import window_constraints
    monkeypatch.setattr(env.owner,'showMinimized',lambda:calls.append('min'))
    monkeypatch.setattr(env.owner,'showMaximized',lambda:calls.append('max'))
    monkeypatch.setattr(window_constraints,'begin_title_drag',lambda owner,*a,**k:calls.append(('drag',owner)))
    bar.minimize_button.click();bar.maximize_button.click()
    event=QMouseEvent(QEvent.Type.MouseButtonPress,QPointF(12,10),QPointF(100,100),
                      Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    bar.mousePressEvent(event)
    assert calls[:2]==['min','max'] and calls[-1]==('drag',env.owner)
    assert bar._window is env.owner and bar.parentWidget() is env.session.view and not bar.isWindow()


def test_cover_close_control_closes_the_owner_not_just_the_card(native_session):
    env=native_session;env.session.begin('A')
    env.session.view.window_title_bar.close_button.click()
    assert not env.owner.isVisible()


def test_real_Qt_full_paint_confirms_only_current_geometry(monkeypatch):
    monkeypatch.setattr(cover,'native_cover_supported',lambda owner:True)
    owner=QWidget();owner.resize(900,700)
    view=StudioLoadingView(owner,owner,native_cover=True,owner=owner)
    view.apply_theme();view.sync_geometry();owner.show();view.show();APP.processEvents();view.repaint()
    view._confirm_native_paint(notify=False)
    assert view._cover_submitted_stamp==view._cover_stamp(), (view._cover_painted_stamp,view._cover_painted_region)
    view._invalidate_native_paint()
    assert view._cover_submitted_stamp is None
    # A partial paint alone cannot satisfy a fresh complete-frame witness.
    view._cover_painted_stamp=view._cover_stamp()
    from PySide6.QtGui import QRegion
    view._cover_painted_region=QRegion(0,0,20,20)
    view._confirm_native_paint(notify=False)
    assert view._cover_submitted_stamp is None
    owner.close();owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_input_host_cannot_contain_the_cover_or_belong_to_another_root():
    owner=QWidget();view=QWidget(owner);other=QWidget();foreign=QWidget(other)
    assert not cover.InputHostLease(owner).acquire(owner,view)
    assert not cover.InputHostLease(foreign).acquire(owner,view)
    assert owner.isEnabled() and foreign.isEnabled()
    owner.deleteLater();other.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_input_lease_restores_own_enabled_state_without_overriding_disabled_ancestor():
    owner=QWidget();pages=QWidget(owner);view=QWidget(owner);owner.setEnabled(False)
    lease=cover.InputHostLease(pages)
    assert lease.acquire(owner,view)
    lease.release()
    assert not pages.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled) and not pages.isEnabled()
    owner.setEnabled(True);assert pages.isEnabled()
    owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_read_only_evidence_never_creates_a_native_handle():
    class NoCreation(QWidget):
        def winId(self):raise AssertionError('observer attempted native creation')
    owner=NoCreation();view=NoCreation(owner)
    before=[w.testAttribute(Qt.WidgetAttribute.WA_WState_Created)for w in (owner,view)]
    api=NS(observe=lambda *a:(_ for _ in ()).throw(AssertionError('uncreated windows observed')))
    state=cover.native_cover_state(view,owner,requested=True,supported=True,
        complete_paint=True,opaque_background=True,_api=api)
    assert not state['verified'] and state['reasons']==['native handles not created']
    assert before==[w.testAttribute(Qt.WidgetAttribute.WA_WState_Created)for w in (owner,view)]
    owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_existing_nonraster_root_falls_back_without_creating_a_handle(monkeypatch):
    owner=QWidget()
    monkeypatch.setattr(cover.sys,'platform','win32')
    monkeypatch.setattr(cover,'QApplication',NS(instance=lambda:NS(platformName=lambda:'windows')))
    monkeypatch.setattr(owner,'windowHandle',lambda:NS(surfaceType=lambda:NS(name='Direct3DSurface')))
    assert not cover.native_cover_supported(owner)
    assert not owner.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
    owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.fixture
def observed_cover(monkeypatch):
    owner=QWidget();owner.resize(500,400)
    view=QWidget(owner);view.setAttribute(Qt.WidgetAttribute.WA_NativeWindow);view.setGeometry(owner.rect())
    owner.show();view.show();APP.processEvents()
    fake_window=NS(format=lambda:NS(alphaBufferSize=lambda:8),surfaceType=lambda:NS(name='RasterSurface'))
    monkeypatch.setattr(view,'windowHandle',lambda:fake_window)
    native=dict(child_pid=os.getpid(),root_pid=os.getpid(),parent=cover.existing_handle(owner),
        style=0x50000000,ex_style=0x80000,root_ex_style=0,child_visible=True,root_visible=True,
        root_minimized=False,child_rect=[0,0,500,400],root_client_rect=[0,0,500,400],
        first_visible_root_child=cover.existing_handle(view),root_children=[],root_children_truncated=False,
        native_region_full=True,native_region_kind=0,native_region_error=0)
    api=NS(observe=lambda *a:dict(native))
    def inspect(**kwargs):
        return cover.native_cover_state(view,owner,requested=True,supported=True,
            complete_paint=kwargs.get('paint',True),opaque_background=kwargs.get('opaque',True),_api=api)
    yield native,inspect
    owner.close();owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_valid_observation_is_explicitly_submission_not_scanout(observed_cover):
    _,inspect=observed_cover;state=inspect()
    assert state['verified'] and 'not physical presentation' in state['measurement']


@pytest.mark.parametrize('mutation',['foreign_pid','foreign_parent','popup','not_layered','layered_root',
                                   'covered_by_sibling','short_rectangle','empty_region','minimized'])
def test_native_coverage_rejects_incomplete_or_foreign_evidence(observed_cover,mutation):
    native,inspect=observed_cover
    if mutation=='foreign_pid':native['child_pid']+=1
    elif mutation=='foreign_parent':native['parent']=0
    elif mutation=='popup':native['style']|=0x80000000
    elif mutation=='not_layered':native['ex_style']=0
    elif mutation=='layered_root':native['root_ex_style']=0x80000
    elif mutation=='covered_by_sibling':native['first_visible_root_child']=0
    elif mutation=='short_rectangle':native['child_rect'][2]-=1
    elif mutation=='empty_region':native['native_region_full']=False
    else:native['root_minimized']=True
    assert not inspect()['verified']


@pytest.mark.parametrize('field',['paint','opaque'])
def test_native_identity_does_not_replace_complete_opaque_paint(observed_cover,field):
    _,inspect=observed_cover
    assert not inspect(**{field:False})['verified']
