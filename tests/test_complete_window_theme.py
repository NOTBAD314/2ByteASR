"""Visible style regressions, independent of internal scope bookkeeping."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication,QFrame,QLabel,QStackedWidget,QVBoxLayout,QWidget
from twobyteasr.design import theme_scopes


@pytest.fixture
def ui(monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    messages=[];old=qInstallMessageHandler(lambda kind,ctx,message:messages.append(str(message)))
    yield app,messages
    for w in app.topLevelWidgets():w.close()
    app.processEvents();qInstallMessageHandler(old)
    assert not [m for m in messages if 'Could not parse' in m and 'stylesheet' in m]


def setup(app,monkeypatch,sheet):
    monkeypatch.setattr(app,'_theme_window_qss',sheet,raising=False)
    monkeypatch.setattr(app,'_applied_theme_key','probe-'+str(id(sheet)),raising=False)
    root=QWidget();root.setObjectName('applicationSettings');root.resize(360,280)
    QVBoxLayout(root);return root


def settle(app):
    for _ in range(8):app.processEvents()


def pixel(widget):
    image=widget.grab().toImage();return image.pixelColor(image.width()//2,image.height()//2).name()


def test_real_home_sheet_with_comma_comments_keeps_icon_chip(ui,monkeypatch):
    app,_=ui
    from twobyteasr.design.theme_manager import _global_qss
    from twobyteasr.design.main_ui_theme import APP_QSS
    from twobyteasr.design.qss_retheme import retheme_qss
    from twobyteasr.design.ui_theme import theme_definition
    from twobyteasr.design.studio_theme import build_secondary_surface_qss
    t=theme_definition('sand')
    sheet=retheme_qss(APP_QSS,t)+_global_qss(t)+build_secondary_surface_qss(t)
    root=setup(app,monkeypatch,sheet)
    label=QLabel('');label.setObjectName('homeAiIcon');label.setFixedSize(54,54);root.layout().addWidget(label)
    theme_scopes.refresh(root);root.show();settle(app)
    assert pixel(label)==t.accent


@pytest.mark.parametrize('large',[False,True])
def test_stacked_or_large_parent_keeps_own_surface(ui,monkeypatch,large):
    app,_=ui;root=setup(app,monkeypatch,'QFrame#plate {background:#901122; border:0;}')
    plate=QFrame();plate.setObjectName('plate');root.layout().addWidget(plate)
    layout=QVBoxLayout(plate);layout.setContentsMargins(24,24,24,24)
    if large:
        for _ in range(100):QLabel('',plate)
    stack=QStackedWidget();stack.addWidget(QWidget());layout.addWidget(stack)
    theme_scopes.refresh(root);root.show();settle(app)
    assert plate.grab().toImage().pixelColor(12,12).name()=='#901122'


def test_native_local_inline_override_is_not_rewritten(ui,monkeypatch):
    app,_=ui;root=setup(app,monkeypatch,'QLabel#local {color:#223344; background:#ddeeff;}')
    label=QLabel('Inline');label.setObjectName('local');local='color:#ee1122; padding:4px;'
    label.setStyleSheet(local);root.layout().addWidget(label)
    theme_scopes.refresh(root);root.show();settle(app)
    assert label.styleSheet()==local
    assert label.palette().color(QPalette.ColorRole.WindowText).name()=='#ee1122'


def test_quoted_comments_commas_braces_and_late_children_use_qt_parser(ui,monkeypatch):
    app,_=ui
    sheet='''/* A comment, with punctuation. */
QLabel[kind="a,b c"] { qproperty-text: "literal /*,*/ {x}"; background:#124578; }
QFrame#late {background:#239856; border:0;}'''
    root=setup(app,monkeypatch,sheet)
    label=QLabel();label.setProperty('kind','a,b c');root.layout().addWidget(label)
    theme_scopes.refresh(root);root.show();settle(app)
    assert label.text()=='literal /*,*/ {x}'
    assert pixel(label)=='#124578'
    late=QFrame();late.setObjectName('late');late.setFixedSize(60,30);root.layout().addWidget(late);late.show();settle(app)
    assert pixel(late)=='#239856'


def test_repeated_changes_do_not_capture_generated_sheets_or_change_child_qss(ui,monkeypatch):
    app,_=ui;root=setup(app,monkeypatch,'QFrame#plate {background:#aabbcc;}')
    child=QFrame();child.setObjectName('plate');root.layout().addWidget(child)
    root.show()
    for index,colour in enumerate(['#aabbcc','#112233']*4):
        monkeypatch.setattr(app,'_theme_window_qss','QFrame#plate {background:'+colour+';}')
        monkeypatch.setattr(app,'_applied_theme_key','round-'+str(index))
        theme_scopes.refresh(root);settle(app)
        assert pixel(child)==colour
        assert child.styleSheet()==''
        assert len(root.styleSheet())<100


def test_hidden_home_owner_catches_up_when_returning_from_studio():
    from twobyteasr.design.theme_manager import apply_theme,theme_definition
    app=QApplication.instance() or QApplication([])
    root=QWidget();layout=QVBoxLayout(root);stack=QStackedWidget();layout.addWidget(stack)
    home=QWidget();QVBoxLayout(home);home_icon=QLabel('');home_icon.setObjectName('homeAiIcon');home_icon.setFixedSize(54,54);home.layout().addWidget(home_icon)
    studio=QWidget();studio.setObjectName('subtitleStudio');QVBoxLayout(studio)
    studio._set_hub_toolbar_mode=lambda hub:None
    studio_icon=QLabel('');studio_icon.setObjectName('homeAiIcon');studio_icon.setFixedSize(54,54);studio.layout().addWidget(studio_icon)
    stack.addWidget(home);stack.addWidget(studio)
    root.pages=stack;root._studio_page_instance=studio;root.built_page=lambda name:studio if name=='studio' else None
    root.show();apply_theme('sand');settle(app)
    old=root.styleSheet();stack.setCurrentWidget(studio);settle(app)
    apply_theme('grape');settle(app)
    assert root.styleSheet()==old and root._theme_full_sheet_pending
    assert pixel(studio_icon)==theme_definition('grape').accent
    stack.setCurrentWidget(home);settle(app)
    assert pixel(home_icon)==theme_definition('grape').accent
    assert not root._theme_full_sheet_pending
    root.close()
