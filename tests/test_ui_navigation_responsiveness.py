"""Regression tests for work proved by the headed navigation benchmark."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def make_dialog(tmp_path):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    return ApplicationSettingsDialog(None, {'auto_cover': False, 'restore_layout': False},
        tmp_path/'Projects', browse=lambda *args: None, clear_recent=lambda: None,
        reset_layout=lambda: None)


def test_settings_only_builds_selected_category_and_preserves_earlier_edits(app,tmp_path,monkeypatch):
    dialog=make_dialog(tmp_path)
    assert dialog._section_built == {0}
    assert not hasattr(dialog,'shortcut_panel')
    assert not hasattr(dialog,'storage_panel')
    original=dialog.root_edit.text()
    dialog.root_edit.setText(original+'-edited')
    dialog.ensure_section('Studio 与维护')
    assert not dialog.cover.isChecked()
    assert not dialog.restore_layout_box.isChecked()
    assert dialog._values() != dialog._saved_values
    dialog.root_edit.setText(original)
    assert dialog._values() == dialog._saved_values
    asked=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *args:asked.append(args) or QMessageBox.Cancel)
    dialog.reject()
    assert not asked
    dialog.deleteLater()


def test_unvisited_preferences_survive_save_and_active_guard_is_cleared(app,tmp_path,monkeypatch):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from PySide6.QtWidgets import QDialog
    writes=[]
    monkeypatch.setattr(settings,'read_studio_preferences',lambda:{'auto_cover':False,
        'restore_layout':False,'recent_project_count':17,'reduce_motion':True})
    monkeypatch.setattr(settings,'save_hub_preferences',lambda *args:writes.append(args))
    monkeypatch.setattr(ApplicationSettingsDialog,'exec',lambda self:QDialog.Accepted)
    parent=QWidget()
    assert settings.open_application_settings(parent)
    assert writes[-1][3:6] == (17,False,False)
    assert writes[-1][7] is True
    assert parent._application_settings_dialog is None


def test_reentrant_settings_entry_reuses_active_instance(app,monkeypatch):
    from twobyteasr.app import application_settings as settings
    parent=QWidget();calls=[]
    parent._application_settings_dialog=SimpleNamespace(raise_=lambda:calls.append('raise'),
        activateWindow=lambda:calls.append('activate'))
    assert not settings.open_application_settings(parent)
    assert calls==['raise','activate']


def test_unchanged_settings_reuse_one_dialog_and_config_changes_invalidate(app,monkeypatch):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    from PySide6.QtWidgets import QDialog
    parent=QWidget();opened=[];preferences={'autosave_enabled':True}
    monkeypatch.setattr(settings,'read_studio_preferences',lambda:dict(preferences))
    monkeypatch.setattr(ApplicationSettingsDialog,'exec',lambda dialog:opened.append(dialog) or QDialog.Rejected)
    settings.open_application_settings(parent);settings.open_application_settings(parent)
    assert opened[0] is opened[1]
    preferences['autosave_enabled']=False
    settings.open_application_settings(parent)
    assert opened[2] is not opened[0] and not opened[2].auto_save.isChecked()
    parent.deleteLater()


def test_home_navigation_keeps_project_session_and_pauses_playback():
    from twobyteasr.studio.studio_project_flow import StudioProjectFlowMixin
    session=object();project=object();calls=[]
    page=SimpleNamespace(project=project,session=session,project_path='test.2byteproj',
        _readiness=SimpleNamespace(active=False),
        video=SimpleNamespace(set_paused=lambda value:calls.append(('paused',value))),
        _close_export_workspace=lambda:calls.append('close_export'),
        _studio_trace=lambda *args,**kwargs:None,
        return_requested=SimpleNamespace(emit=lambda:calls.append('home')))
    StudioProjectFlowMixin._request_return_home(page)
    assert page.project is project and page.session is session
    assert calls==[('paused',True),'close_export','home']


def test_navigation_polling_restores_only_previously_running_timers(app):
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=SimpleNamespace(_timer=QTimer(),_sync_timer=QTimer())
    canvas._timer.start(17);canvas._sync_timer.setInterval(150)
    MpvCanvas.set_navigation_visible(canvas,False)
    MpvCanvas.set_navigation_visible(canvas,False)
    assert not canvas._timer.isActive() and not canvas._sync_timer.isActive()
    MpvCanvas.set_navigation_visible(canvas,True)
    assert canvas._timer.isActive() and canvas._timer.interval()==17
    assert not canvas._sync_timer.isActive()
    canvas._timer.stop()


def test_incremental_shortcuts_preserve_imports_and_defaults_before_rows_exist(app,tmp_path):
    from twobyteasr.studio import shortcut_registry as registry
    from twobyteasr.studio.studio_shortcuts import ShortcutSettingsPanel
    panel=ShortcutSettingsPanel(registry.current_values(),scopes=tuple(registry.SCOPE_LABELS),
        embedded=True,incremental=True)
    target=panel._actions[-1].id
    assert target not in panel.rows and not panel.construction_complete
    bindings=panel.values();bindings[target]='Ctrl+Alt+F12'
    path=tmp_path/'import.json';path.write_text(registry.export_payload(bindings),'utf8')
    assert panel.import_file(str(path))
    assert registry.import_payload(registry.export_payload(panel.values()))[target]=='Ctrl+Alt+F12'
    panel._restore_defaults()
    assert panel.values()[target]==registry.normalize(panel._defaults.get(target,''))
    assert panel.import_file(str(path))
    panel.show()
    import time
    from PySide6.QtTest import QTest
    deadline=time.monotonic()+5
    while not panel.construction_complete and time.monotonic()<deadline:
        QTest.qWait(10)
    assert panel.construction_complete
    assert panel.rows[target].value()=='Ctrl+Alt+F12'
    assert len(panel.rows)==len(panel._actions)
    panel.close()


def test_bilingual_readiness_uses_current_display_rows_and_rejects_old_pixels():
    from twobyteasr.rendering.caption_scene import CaptionScene
    token=('project',1,1,1,('source',))
    scene=SimpleNamespace(token=token,last_result_token=token,published=None,metrics=[{
        'expected_cue_ids':['source','source#tr'],
        'cue_pixels':[{'cue_id':key,'status':'rendered'} for key in ('source','source#tr')]}])
    trace=CaptionScene.trace(scene)
    assert trace['expected_cue_ids']==['source']
    assert set(trace['expected_display_cue_ids'])==set(trace['rendered_cue_ids'])=={'source','source#tr'}
    scene.token=('project',1,2,1,('next',))
    trace=CaptionScene.trace(scene)
    assert trace['expected_display_cue_ids']==['next'] and trace['cue_pixels']==[]


def test_completed_waveform_drops_late_progress_without_claiming_save_success(app):
    from PySide6.QtWidgets import QLabel
    from twobyteasr.studio.studio_media_flow import StudioMediaFlowMixin
    label=QLabel('正在生成音频波形… 88%')
    page=SimpleNamespace(_waveform_generation=4,_waveform_last_progress_text=label.text(),save_state=label,
        timeline=SimpleNamespace(set_cache=lambda cache:None,set_waveform_state=lambda *a:None),
        _studio_mark_startup_milestone=lambda *a,**kw:None,_start_next_project_waveform=lambda *a:None)
    StudioMediaFlowMixin._waveform_ready(page,4,'media','full',object())
    assert label.text()=='波形已就绪'
    StudioMediaFlowMixin._waveform_progress(page,4,'media','正在生成音频波形… 93%')
    assert label.text()=='波形已就绪'
    label.setText('正在保存…')
    StudioMediaFlowMixin._waveform_ready(page,4,'media','full',object())
    assert label.text()=='正在保存…'
