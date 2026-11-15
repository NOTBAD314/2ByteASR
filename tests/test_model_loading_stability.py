"""Regression cases for accidental top-level controls and atomic model reveal."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QScrollArea, QVBoxLayout

APP = QApplication.instance() or QApplication([])


def test_home_without_snapshot_requests_background_scan_and_keeps_saved_keys(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.local_models import model_status_cache
    requests=[]
    monkeypatch.setattr(model_status_cache,'cached_registry',lambda _:None)
    monkeypatch.setattr(model_status_cache,'request_registry',lambda root:requests.append(root))
    window=SimpleNamespace(_home_installed_model_keys={'saved-local-model'})
    assert MainWindow._cached_home_model_keys(window)=={'saved-local-model'}
    assert len(requests)==1
    fresh=SimpleNamespace()
    assert MainWindow._cached_home_model_keys(fresh)==set()


def test_cloud_picker_never_shows_a_parentless_configure_button():
    from twobyteasr.local_models.model_picker_cards import PickerCard
    from twobyteasr.local_models.model_workshop import MODELS
    shown=[]
    class Observer(QObject):
        def eventFilter(self, obj, event):
            if event.type()==QEvent.Type.Show and isinstance(obj,QWidget) and obj.isWindow():
                shown.append((type(obj).__name__,obj.objectName()))
            return False
    observer=Observer()
    APP.installEventFilter(observer)
    host=QWidget()
    model=next(m for m in MODELS if m.api_preset)
    try:
        card=PickerCard(model,'primary',recommended=False,logo=lambda *_:None,
            accuracy={},online=True,parent=host)
        card.set_state_badge('未配置')
        assert not shown
        assert card.configure.parentWidget() is card
        assert not card.configure.isWindow()
        assert card.parentWidget() is host
    finally:
        APP.removeEventFilter(observer)
        host.deleteLater()


def test_timeline_scope_note_never_becomes_a_top_level_window(tmp_path,monkeypatch):
    from twobyteasr.local_models import model_status_cache
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage,ModelPickerPanel
    monkeypatch.setattr(model_status_cache,'request_registry',lambda *a,**kw:None)
    shown=[]
    class Observer(QObject):
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Show and isinstance(obj,QWidget) and obj.isWindow():
                shown.append(type(obj).__name__)
            return False
    observer=Observer();APP.installEventFilter(observer)
    page=ModelWorkshopPage(tmp_path,{'models':{}},defer_ui=True)
    try:
        panel=ModelPickerPanel(page,'timeline',page)
        assert panel.scope_note.parentWidget() is panel and not shown
    finally:
        APP.removeEventFilter(observer)
        page.deleteLater()


def test_reveal_finishes_full_list_and_cached_reopen_has_no_veil():
    from twobyteasr.local_models.model_loading_surface import ModelListReveal
    from twobyteasr.local_models.model_workshop import _DeferredModelCard
    class Card(_DeferredModelCard):
        def _make_card(self):
            # Production materialize is covered by normal-window acceptance;
            # this case isolates page hide/reopen and generation cancellation.
            return QWidget(self)
        def materialize(self):
            if self._card is None:
                self._card=self._make_card()
                self.layout().addWidget(self._card)
            return self._card
    scroll=QScrollArea()
    host=QWidget()
    layout=QVBoxLayout(host)
    cards={str(i):Card(None,host) for i in range(19)}
    for card in cards.values():layout.addWidget(card)
    scroll.setWidget(host)
    reveal=ModelListReveal(scroll,cards)
    scroll.resize(500,400)
    scroll.show()
    APP.processEvents()
    scroll.hide()
    first_generation=reveal.generation
    scroll.show()
    deadline=time.monotonic()+3
    while not reveal.ready and time.monotonic()<deadline:
        APP.processEvents()
        time.sleep(.002)
    assert reveal.ready
    assert all(c._card is not None for c in cards.values())
    scroll.hide()
    scroll.show()
    APP.processEvents()
    assert reveal.generation>first_generation
    assert not reveal.veil.isVisible()
    assert not reveal.timer.isActive()
    scroll.close()
    scroll.deleteLater()


def test_managed_studio_has_one_unscaled_window_sheet_and_no_recursive_apply(monkeypatch):
    from twobyteasr.design import theme_scopes
    from twobyteasr.app import ui_zoom
    from twobyteasr.design import studio_theme
    monkeypatch.setattr(APP,'_theme_window_qss','QWidget { font-size: 13px; }',raising=False)
    monkeypatch.setattr(studio_theme,'build_studio_qss',lambda *_:'QLabel { color: red; }')
    monkeypatch.setattr(ui_zoom,'zoom_percent',lambda:120)
    monkeypatch.setattr(ui_zoom,'zoom_factor',lambda:1.2)
    class Studio(QWidget):
        def __init__(self):
            super().__init__()
            self.calls=0
        def setStyleSheet(self,sheet):
            self.calls+=1
            theme_scopes.apply_scope(self)  # simulate a synchronous native style callback
            super().setStyleSheet(sheet)
    page=Studio()
    page.setObjectName('subtitleStudio')
    theme_scopes.prepare(page)
    theme_scopes.apply_scope(page)
    ui_zoom.protect_studio(page)
    assert page.calls==1
    assert page.styleSheet().count('font-size: 13px')==1
    assert page.styleSheet().endswith('QLabel { color: red; }')
    page.deleteLater()
