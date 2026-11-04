"""Regression for cover-bearing first entry, partial binding and late callbacks."""
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent,QCoreApplication,QTimer
from PySide6.QtGui import QImage,QResizeEvent
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest

from tests.test_page_open_library import library,_page_with_index,_wait_scan
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.studio.studio_loading import StudioLoadingSession


def test_cover_container_exists_before_first_filter_and_survives_rebuild(library):
    page=SubtitleStudioPage(deferred_build=True)
    try:
        assert page._library_cover_labels=={} and not page._hub_ui_ready
        assert page.eventFilter(QWidget(),QEvent(QEvent.User)) is False
        page.finish_workspace_construction();page.resize(1400,900);page.show();page.show_project_hub();_wait_scan(page)
        image=QImage(100,60,QImage.Format_ARGB32);image.fill(0xff781845)
        cover=library/'cover.png';assert image.save(str(cover))
        rows=[dict(r,cover_path=str(cover)) for r in page._hub_library_records]
        page._hub_library_records=rows;page._rebuild_project_library();_wait_scan(page)
        assert page._hub_card_widgets and page._resume_has_cover
        labels=page._library_cover_labels
        page._hub_render_signature=None;page._rebuild_project_library();_wait_scan(page)
        assert page._library_cover_labels is labels
        assert len(page._hub_card_widgets)==len(rows)
    finally:page.close_page()


def test_failed_bind_is_not_cached_and_retry_really_populates(library,monkeypatch):
    page=_page_with_index(library)
    try:
        page.show_project_hub();_wait_scan(page)
        original=page._update_resume_project
        page._hub_render_signature=None
        def broken(*a):raise RuntimeError('controlled binding error')
        monkeypatch.setattr(page,'_update_resume_project',broken)
        with pytest.raises(RuntimeError,match='binding error'):page._rebuild_project_library()
        assert page._hub_render_signature is None and not page._hub_rebuilding
        monkeypatch.setattr(page,'_update_resume_project',original)
        page._rebuild_project_library();_wait_scan(page)
        assert len(page._hub_card_widgets)==len(page._hub_display_records)>0
    finally:page.close_page()


def test_stale_scan_cannot_clear_current_pending_or_replace_rows(library):
    page=_page_with_index(library)
    try:
        page.show_project_hub();_wait_scan(page)
        original=page._hub_library_records
        page._hub_scan_generation=99;page._hub_scan_active_generation=99;page._hub_scan_pending=True
        page._library_scan_ready([],98)
        assert page._hub_scan_pending and page._hub_library_records is original
        page._library_scan_ready({'error':'old failure'},98)
        assert page._library_load_state!='failed'
        page._hub_scan_pending=False
    finally:page.close_page()


def test_presence_timeout_does_not_hold_list_and_late_result_ignored(library,monkeypatch):
    import threading
    page=_page_with_index(library);release=threading.Event()
    try:
        page.show_project_hub();_wait_scan(page)
        QTest.qWait(100)
        def slow(rows):release.wait(2);return {r['path']:(True,False) for r in rows}
        monkeypatch.setattr(page,'_check_library_presence',slow)
        page._start_library_presence(page._hub_library_records)
        token=page._library_presence_generation
        page._library_presence_timer.start(25);QTest.qWait(75)
        assert page._library_presence_timed_out and page._hub_card_widgets
        values=dict(getattr(page,'_library_presence',{}));release.set();QTest.qWait(100)
        page._library_presence_ready({'old':(False,False)},token)
        assert page._library_presence==values
    finally:release.set();page.close_page()


def test_empty_no_results_failure_are_distinct_and_failure_keeps_content(library):
    page=_page_with_index(library)
    try:
        page.show_project_hub();_wait_scan(page)
        generation=page._hub_scan_generation
        page._library_scan_ready({'error':'工程库读取失败：controlled'},generation)
        assert page.hub_loading_label.isVisible() and page._hub_card_widgets
        assert not page.project_library_empty.isVisible()
        page._library_scan_ready([],generation)
        assert page.project_library_empty.isVisible() and '还没有工程' in page.project_library_empty.text()
        page.project_search.setText('absent');QTest.qWait(50)
        assert '匹配' in page.project_library_empty.text()
    finally:page.close_page()


def test_loading_elapsed_ticks_and_new_round_resets_without_stage_messages():
    app=QApplication.instance() or QApplication([]);host=QWidget()
    session=StudioLoadingSession(host)
    session.begin('',present=False);initial=session.view.label.text()
    QTest.qWait(350)
    assert session.view.label.text()!=initial
    old=session.generation;session.fail('创建工作台界面','controlled')
    QTest.qWait(120);assert not session._elapsed_timer.isActive()
    session.begin('',present=False)
    assert session.generation==old+1 and session.view.label.text().endswith('0.0s')
    session.abort();QTest.qWait(120);assert not session._elapsed_timer.isActive()
    host.close()


def test_verified_reused_cover_starts_queued_retry_without_another_paint():
    from types import SimpleNamespace as NS
    from twobyteasr.app.ui import MainWindow
    events=[]
    session=NS(active=True,stage=lambda *a:None,view=NS(update=lambda:events.append('update')))
    host=NS(_prepare_studio_loading=lambda *a,**k:session,
            _loading_surface_painted=lambda:events.append('check-existing-paint'))
    MainWindow._queue_studio_construction(host,None,mode='hub')
    assert host._studio_entry_pending==(None,{'mode':'hub'})
    assert host._studio_entry_start_queued
    assert events==['update','check-existing-paint']


def test_repeated_retry_clicks_start_only_one_new_generation():
    app=QApplication.instance() or QApplication([]);host=QWidget();calls=[]
    session=StudioLoadingSession(host)
    def retry():calls.append(1);session.begin('',present=False)
    session.begin('',on_retry=retry,present=False);session.fail('创建工作台界面','controlled')
    generation=session.generation
    for _ in range(5):session.request_retry()
    assert calls==[1] and session.generation==generation+1
    session.abort();host.close()
