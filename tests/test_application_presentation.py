import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QSplitter, QLineEdit
from twobyteasr.design.presentation import field_width
from twobyteasr.design.ui_motion import atomic_layout, motion_duration


@pytest.fixture
def app(tmp_path,monkeypatch):
    instance=QApplication.instance() or QApplication([])
    from twobyteasr.design import theme_manager
    monkeypatch.setattr(theme_manager,'_settings',lambda:QSettings(str(tmp_path/'theme.ini'),QSettings.Format.IniFormat))
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    return instance


def test_atomic_first_frame_commits_hidden_splitter_children(app):
    root=QWidget();layout=QHBoxLayout(root);split=QSplitter(Qt.Orientation.Horizontal)
    layout.addWidget(split)
    children=[QWidget() for _ in range(3)]
    for child in children:split.addWidget(child)
    root.resize(1000,600);root.show();app.processEvents()
    with atomic_layout(root):
        children[0].hide();children[2].hide();split.setSizes([0,900,0])
    assert split.sizes()==[0,split.width(),0]
    first=split.sizes();app.processEvents();assert split.sizes()==first
    assert root.updatesEnabled()
    root.close()


def test_atomic_boundary_preserves_outer_update_suppression(app):
    root=QWidget();root.setUpdatesEnabled(False)
    with atomic_layout(root):
        with atomic_layout(root):pass
    assert not root.updatesEnabled()
    root.deleteLater()


def test_semantic_fields_let_path_grow_and_bound_short_values(app):
    root=QWidget();row=QHBoxLayout(root)
    short=field_width(QLineEdit('2'),'numeric')
    path=field_width(QLineEdit('D:/项目/录播'),'expanding')
    row.addWidget(short);row.addWidget(path,1)
    root.resize(1200,180);root.show();app.processEvents()
    assert short.width()<=144
    assert path.width()>800
    assert short.height()==path.height()
    root.close()


def test_accent_icon_uses_the_same_foreground_as_text_for_every_theme():
    from twobyteasr.design.themed_icons import icon_role_color
    from twobyteasr.design.ui_theme import THEMES
    for theme in THEMES.values():
        assert icon_role_color('on_accent',theme)==theme.text_on_accent


def test_settings_cancel_has_no_persistence_side_effect(app,monkeypatch):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from PySide6.QtWidgets import QDialog
    writes=[]
    monkeypatch.setattr(settings,'save_hub_preferences',lambda *a,**kw:writes.append(a))
    def reject(dialog):
        dialog.auto_save.setChecked(False)
        dialog.root_edit.setText('D:/not-saved')
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(ApplicationSettingsDialog,'exec',reject)
    parent=QWidget()
    assert settings.open_application_settings(parent) is False
    assert writes==[]


def test_settings_cancel_after_browsing_pages_asks_only_for_real_edits(app,monkeypatch,tmp_path):
    # 2026-10-15: QStackedWidget adds pages at the front of its child list and
    # moves the page it shows to the end, so findChildren() order followed the
    # pages visited and Cancel asked to save after merely browsing.
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from PySide6.QtWidgets import QDialog, QMessageBox
    asked=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:asked.append(str(a[2])) or QMessageBox.StandardButton.Cancel)
    def browsed():
        dialog=ApplicationSettingsDialog(None,{},tmp_path/'Projects',browse=lambda *a:None,
                                         clear_recent=lambda:None,reset_layout=lambda:None)
        for row in range(dialog.navigation.count()):
            dialog.navigation.setCurrentRow(row);app.processEvents()
        return dialog
    dialog=browsed()
    assert dialog._values()==dialog._saved_values
    dialog.reject()
    assert asked==[] and dialog.result()==QDialog.DialogCode.Rejected
    dialog.deleteLater()
    for edit in (lambda d:d.root_edit.setText(str(tmp_path/'Elsewhere')),
                 lambda d:d.recovery_policy.setCurrentIndex(d.recovery_policy.findData('official')),
                 lambda d:d.reduce_motion_box.setChecked(True)):
        dialog=browsed();edit(dialog)
        dialog.navigation.setCurrentRow(2);app.processEvents()
        dialog.reject()
        assert asked==['保存这些设置更改吗？'],asked
        asked.clear();dialog.deleteLater()
    app.processEvents()


def test_settings_save_roundtrips_existing_preferences(app,monkeypatch):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from PySide6.QtWidgets import QDialog
    writes=[]
    monkeypatch.setattr(settings,'read_studio_preferences',lambda:{'recent_project_count':17,'recovery_policy':'official'})
    monkeypatch.setattr(settings,'save_hub_preferences',lambda *args:writes.append(args))
    monkeypatch.setattr(settings,'apply_theme',lambda *a:None)
    def accept(dialog):
        dialog.auto_save.setChecked(True)
        dialog.interval.setCurrentIndex(dialog.interval.findData(120))
        dialog.reduce_motion_box.setChecked(True)
        assert dialog.pages.count()==4
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ApplicationSettingsDialog,'exec',accept)
    assert settings.open_application_settings(QWidget()) is True
    assert writes[0][1:4]==(True,120,17)
    assert writes[0][6:] == ('official',True)
    assert motion_duration(180)==0
    app.setProperty('reduceMotion',False)
