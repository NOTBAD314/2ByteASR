"""Correctness of deferred work, invalidation and monotonic local impacts."""
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QVariantAnimation
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def until(app, predicate, timeout=3):
    deadline = time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def test_registry_requests_merge_and_invalidated_scan_cannot_publish(tmp_path, monkeypatch):
    from twobyteasr.local_models import model_status_cache as cache, model_registry
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []
    def scan(*, install_root):
        calls.append(threading.get_ident())
        if len(calls)==1:
            entered.set()
            assert release.wait(3)
        return SimpleNamespace(value=len(calls))
    monkeypatch.setattr(model_registry, 'scan_model_registry', scan)
    cache.request_registry(tmp_path, results.append)
    assert entered.wait(3)
    cache.request_registry(tmp_path, results.append)
    cache.request_registry(tmp_path, results.append, force=True)
    release.set()
    deadline=time.monotonic()+3
    while not results and time.monotonic()<deadline: time.sleep(.005)
    assert len(calls)==2 and len(results)==1 and results[0].value==2
    assert calls[0] != threading.get_ident()
    assert cache.cached_registry(tmp_path) is results[0]


def test_picker_does_not_construct_workshop_and_reuses_visible_cards(app, tmp_path, monkeypatch):
    from twobyteasr.local_models import model_workshop as mw, model_status_cache
    monkeypatch.setattr(model_status_cache, 'request_registry', lambda *a,**k: None)
    page = mw.ModelWorkshopPage(tmp_path, {'models':{'primary_asr_backend':'moss'}}, defer_ui=True)
    assert not page._ui_built and not page._cards
    panel = mw.ModelPickerPanel(page, 'primary')
    assert not page._ui_built and len(panel.cards)>5
    built = [c for c in panel.cards.values() if c._card is not None]
    assert len(built) == 0
    panel.resize(860,680); panel.show()
    until(app, lambda:any(c._card is not None for c in panel.cards.values()))
    built = [c for c in panel.cards.values() if c._card is not None]
    first = built[0]._card
    page.runtime_settings = {'models':{'primary_asr_backend':'api','qwen_asr_api_provider':'openai'}}
    panel.begin_session()
    assert any(c._card is first for c in panel.cards.values())
    assert 'OpenAI' in panel.current_badge.text()
    panel.deleteLater(); page.deleteLater(); app.processEvents()


def test_workshop_materializes_bounded_initial_rows(app, tmp_path, monkeypatch):
    from twobyteasr.local_models import model_workshop as mw, model_status_cache
    monkeypatch.setattr(model_status_cache, 'request_registry', lambda *a,**k: None)
    page=mw.ModelWorkshopPage(tmp_path, {'models':{}}, defer_ui=True)
    page.ensure_ui()
    assert page._ui_built and len(page._cards)>10
    assert sum(c._card is not None for c in page._cards.values()) <= 2
    page.deleteLater(); app.processEvents()


def test_local_impact_coalesces_and_expires_after_a_long_frame(app, monkeypatch):
    from twobyteasr.app import home_tour as ht
    window=QWidget();window.resize(900,650);window.show()
    tour=ht.GuidedTour(window,[ht.TourStep('test')]);tour.show()
    clock=[100.]
    monkeypatch.setattr(ht,'time',SimpleNamespace(perf_counter=lambda:clock[0]))
    origin=window.geometry()
    tour._shake_window(1,QPointF(1,0))
    begin=tour._shake_started
    clock[0]+=.05;tour._shake_step(.1)
    assert 0 < abs(tour.bubble.mascot.impact_offset.x()) <= 3
    tour._shake_window(1,QPointF(-1,0))
    assert tour._shake_started==begin
    clock[0]+=.25;tour._shake_step(.2)
    assert tour._shake.state()!=QVariantAnimation.State.Running
    assert tour.bubble.mascot.impact_offset==QPointF() and window.geometry()==origin
    tour.close_tour(False);window.close()


def test_corner_is_one_impact_and_both_velocities_turn_inward(app, monkeypatch):
    from twobyteasr.app import home_tour as ht
    window=QWidget();window.resize(900,650);window.show()
    tour=ht.GuidedTour(window,[ht.TourStep('test')]);tour.mode='shown';tour.show()
    tour._undock_mascot()
    hits=[]
    monkeypatch.setattr(tour,'_edge_hit',lambda side,power:hits.append(side))
    limits=tour._puck_limits()
    tour._puck_pos=QPointF(limits.right()-1, limits.bottom()-1)
    tour._puck_v=QPointF(2000,2000)
    tour._puck_last=time.perf_counter()-.02;tour._puck_started=time.perf_counter()
    tour._puck_step()
    assert len(hits)==1 and tour._puck_v.x()<0 and tour._puck_v.y()<0
    tour.close_tour(False);window.close()


def test_initial_history_scan_is_off_gui_thread(app, tmp_path, monkeypatch):
    from twobyteasr.recognition import recognition_history as rh
    entered,release=threading.Event(),threading.Event()
    gui=threading.get_ident()
    def listing(_roots):
        assert threading.get_ident()!=gui
        entered.set();assert release.wait(3)
        return [],[]
    monkeypatch.setattr(rh,'list_report_files',listing)
    page=rh.RecognitionHistoryPage(tmp_path,index_path=tmp_path/'cache.json',async_scan=True)
    assert entered.wait(2)
    assert page.background_busy() and page._built_limit==4
    page.search.setText('still responds')
    release.set()
    until(app,lambda:not page.background_busy())
    assert page.search.text()=='still responds'
    page.deleteLater();app.processEvents()


def test_outdated_history_payload_cannot_restore_deleted_rows(app,tmp_path):
    from twobyteasr.recognition import recognition_history as rh
    page=rh.RecognitionHistoryPage(tmp_path,index_path=tmp_path/'cache.json')
    page._async_scan=True
    page._generation=8
    page._on_parsed(7,{'rows':[(Path('deleted'),1,1,None,'old',True)],'final':False})
    assert 'deleted' not in page._index.entries and not page.records
    page.deleteLater();app.processEvents()


def test_summary_process_preserves_existing_conflict_and_count_rules():
    import json
    from twobyteasr.glossary.terminology import snapshot_from_pairs
    from twobyteasr.glossary.summary_process import summarize
    snapshots=[snapshot_from_pairs([('mist','Alpha'),('mist','Beta'),('old','Fresh')]),
               snapshot_from_pairs([('A','B'),('B','C')])]
    expected = json.loads(json.dumps([item.summary() for item in snapshots]))
    assert summarize(snapshots, threading.Event()) == expected


def test_cancelled_summary_never_starts_a_worker(monkeypatch):
    from twobyteasr.glossary.summary_process import summarize
    from twobyteasr.system import processes
    monkeypatch.setattr(processes,'popen_hidden_subprocess',lambda *a,**k:pytest.fail('cancelled request spawned'))
    cancel=threading.Event();cancel.set()
    with pytest.raises(RuntimeError,match='cancelled'): summarize([],cancel)


def test_registry_capacity_rejects_a_fifth_pending_root_without_growing(tmp_path,monkeypatch):
    from collections import OrderedDict
    from twobyteasr.local_models import model_status_cache as cache
    entries=OrderedDict((str((tmp_path/str(i)).absolute()),dict(pending=True,value=None)) for i in range(4))
    monkeypatch.setattr(cache,'_entries',entries)
    replies=[]
    cache.request_registry(tmp_path/'fifth',replies.append)
    assert len(entries)==4 and replies==[None]


def test_registry_result_already_queued_is_rejected_after_invalidation(tmp_path,monkeypatch):
    from twobyteasr.local_models import model_status_cache as cache
    value=object()
    monkeypatch.setattr(cache,'_entries',{str(tmp_path.absolute()):dict(pending=False,value=value)})
    assert cache.registry_is_current(tmp_path,value)
    cache._entries[str(tmp_path.absolute())]['pending']=True
    assert not cache.registry_is_current(tmp_path,value)


def test_history_reuses_rows_but_refreshes_changed_configuration(app,tmp_path,monkeypatch):
    from twobyteasr.recognition import recognition_history as rh
    page=rh.RecognitionHistoryPage(tmp_path,index_path=tmp_path/'cache.json')
    seen=[]
    monkeypatch.setattr(page,'_ai_service',lambda:'new AI configuration')
    monkeypatch.setattr(page.overview,'update_records',lambda records,service:seen.append(service))
    page._render();page._render()
    assert seen==['new AI configuration']
    page.deleteLater();app.processEvents()


def test_visible_workshop_role_switch_materializes_new_rows(app,tmp_path,monkeypatch):
    from twobyteasr.local_models import model_workshop as mw, model_status_cache
    monkeypatch.setattr(model_status_cache,'request_registry',lambda *a,**k:None)
    page=mw.ModelWorkshopPage(tmp_path,{'models':{}},defer_ui=True)
    page.ensure_ui();page.resize(1300,950);page.show()
    until(app,lambda:all(page.card_layout.itemAt(i).widget()._card is not None for i in (1,2)))
    until(app,lambda:not page._card_viewport.timer.isActive())
    page._set_role('timeline')
    until(app,lambda:all(page.card_layout.itemAt(i).widget()._card is not None for i in (1,2)))
    page.close();page.deleteLater();app.processEvents()


def test_page_change_cancels_feedback_before_navigation_layout(app):
    from twobyteasr.app.home_tour import GuidedTour,TourStep
    window=QWidget();window.resize(900,650);window.show()
    tour=GuidedTour(window,[TourStep('test')]);tour.show()
    tour._shake_window(1,QPointF(1,0))
    assert tour._shake.state()==QVariantAnimation.State.Running
    tour._page_changed(1)
    assert tour._shake.state()!=QVariantAnimation.State.Running
    assert tour.bubble.mascot.impact_offset==QPointF()
    tour.close_tour(False);window.close()
