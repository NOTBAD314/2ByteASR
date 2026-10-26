"""Regression tests for work proved by the headed navigation benchmark."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_message_boxes(monkeypatch):
    """An error box (e.g. the settings lifecycle guard's) would block offscreen."""
    def fail(*args,**kwargs):
        raise AssertionError('unexpected message box: '+' / '.join(str(arg) for arg in args[1:3]))
    for name in ('warning','information','critical'):
        monkeypatch.setattr(QMessageBox,name,fail)


def make_dialog(tmp_path,preferences=None,**kwargs):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    return ApplicationSettingsDialog(None,{'auto_cover':False,'restore_layout':False} if preferences is None else preferences,
        tmp_path/'Projects',browse=lambda *args:None,clear_recent=lambda:None,
        reset_layout=lambda:None,**kwargs)


def write_preferences(preferences):
    import json
    from twobyteasr.projects.studio_project import studio_settings_path
    path=studio_settings_path();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'studio_preferences':preferences}),'utf8')
    return path


def settings_exec(monkeypatch,behave):
    """Replace the modal loop; ``behave(dialog)`` returns the dialog code."""
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    opened=[]
    monkeypatch.setattr(ApplicationSettingsDialog,'exec',lambda dialog:opened.append(dialog) or behave(dialog))
    return opened


def test_settings_only_builds_selected_category_and_preserves_earlier_edits(app,tmp_path,monkeypatch):
    dialog=make_dialog(tmp_path)
    assert dialog._section_built=={0}
    for name in ('cover','storage_panel','theme_gallery','shortcut_panel','mcp_enabled','update_reminder_box'):
        assert name not in dialog.__dict__
    original=dialog.root_edit.text()
    dialog.root_edit.setText(original+'-edited')
    dialog.ensure_section('Studio 与维护')
    assert dialog.pages.currentIndex()==1 and dialog._section_built=={0,1}
    assert not dialog.cover.isChecked() and not dialog.restore_layout_box.isChecked()
    assert dialog.root_edit.text()==original+'-edited'
    assert dialog._values()!=dialog._saved_values
    dialog.root_edit.setText(original)
    assert dialog._values()==dialog._saved_values
    asked=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *args:asked.append(args) or QMessageBox.Cancel)
    dialog.reject()
    assert not asked
    dialog.deleteLater()


def test_reading_a_category_control_builds_that_category_only(app,tmp_path):
    from PySide6.QtWidgets import QLabel
    # 7 is not an offered track count: repaired in memory, warned on the first page.
    dialog=make_dialog(tmp_path,{'speaker_main_tracks':7,'update_reminder':False})
    labels=[dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
    assert labels==['工程与保存','Studio 与维护','存储与缓存','外观','快捷键','外部 AI（MCP）','关于']
    assert dialog.pages.count()==len(labels)
    assert any('部分旧设置无效' in label.text() for label in dialog.pages.widget(0).findChildren(QLabel))
    assert dialog.update_reminder_box.isChecked() is False
    assert dialog._section_built=={0,6} and dialog.pages.currentIndex()==0
    assert dialog.speaker_tracks.currentData()==2
    assert dialog._section_built=={0,1,6}
    assert dialog._values()==dialog._saved_values
    dialog.deleteLater()


def test_saving_without_visiting_a_category_keeps_its_stored_values(app,monkeypatch):
    import json
    from PySide6.QtWidgets import QDialog
    from twobyteasr.app import application_settings as settings
    from twobyteasr.local_mcp import mcp_common
    stored={'auto_cover':False,'restore_layout':False,'recent_project_count':17,'reduce_motion':True,
            'speaker_main_tracks':5,'update_reminder':False,'autosave_enabled':True}
    path=write_preferences(stored)
    mcp_before=mcp_common.read_settings()
    built=[]
    def save(dialog):
        built.append(set(dialog._section_built))
        dialog.auto_save.setChecked(False)
        dialog.accept()
        return QDialog.DialogCode.Accepted
    opened=settings_exec(monkeypatch,save)
    parent=QWidget()
    assert settings.open_application_settings(parent)
    saved=json.loads(path.read_text('utf8'))['studio_preferences']
    assert {key:saved[key] for key in stored}=={**stored,'autosave_enabled':False}
    assert built==[{0}] and opened[0]._section_built=={0}
    assert mcp_common.read_settings()==mcp_before
    assert parent._application_settings_dialog is None
    parent.deleteLater()


def test_unchanged_settings_reuse_one_dialog_and_input_changes_rebuild(app,monkeypatch):
    from PySide6.QtWidgets import QDialog
    from twobyteasr.app import application_settings as settings
    from twobyteasr.studio import shortcut_registry
    write_preferences({'autosave_enabled':True})
    opened=settings_exec(monkeypatch,lambda dialog:QDialog.DialogCode.Rejected)
    parent=QWidget()
    assert not settings.open_application_settings(parent)
    opened[0].ensure_section('外观')
    assert not settings.open_application_settings(parent)
    assert opened[1] is opened[0] and opened[0].pages.currentIndex()==0
    assert parent._application_settings_dialog is None
    settings.open_application_settings(parent,initial_section='快捷键')
    assert opened[2] is opened[0] and opened[0].pages.currentIndex()==4
    write_preferences({'autosave_enabled':False})
    settings.open_application_settings(parent)
    assert opened[3] is not opened[0] and not opened[3].auto_save.isChecked()
    values=shortcut_registry.current_values()
    action=sorted(values)[0];values[action]='Ctrl+Alt+Shift+F11'
    shortcut_registry.save_values(values)
    settings.open_application_settings(parent)
    assert opened[4] is not opened[3]
    settings.open_application_settings(parent,reset_layout=lambda:None)   # adds the 重置布局 row
    assert opened[5] is not opened[4]
    parent.deleteLater()


def test_settings_left_changed_or_saved_are_not_reused(app,monkeypatch):
    from PySide6.QtWidgets import QDialog
    from twobyteasr.app import application_settings as settings
    write_preferences({'autosave_enabled':True})
    parent=QWidget()
    def edit_and_cancel(dialog):
        dialog.interval.setCurrentIndex(0)
        return QDialog.DialogCode.Rejected
    opened=settings_exec(monkeypatch,edit_and_cancel)
    settings.open_application_settings(parent)
    settings.open_application_settings(parent)
    assert opened[1] is not opened[0]
    def scanned(dialog):
        dialog.storage_panel.scan_result=object()
        return QDialog.DialogCode.Rejected
    opened=settings_exec(monkeypatch,scanned)
    settings.open_application_settings(parent)
    settings.open_application_settings(parent)
    assert opened[1] is not opened[0]
    def save(dialog):
        dialog.accept()
        return QDialog.DialogCode.Accepted
    opened=settings_exec(monkeypatch,save)
    settings.open_application_settings(parent)
    settings.open_application_settings(parent)
    assert opened[1] is not opened[0]
    parent.deleteLater()


def test_reused_dialog_calls_this_openings_callbacks(app,monkeypatch):
    from PySide6.QtWidgets import QDialog, QPushButton
    from twobyteasr.app import application_settings as settings
    write_preferences({})
    opened=settings_exec(monkeypatch,lambda dialog:QDialog.DialogCode.Rejected)
    parent=QWidget();calls=[]
    settings.open_application_settings(parent,refresh_library=lambda:calls.append('library-1'),
                                       reset_layout=lambda:calls.append('layout-1'))
    settings.open_application_settings(parent,refresh_library=lambda:calls.append('library-2'),
                                       reset_layout=lambda:calls.append('layout-2'))
    assert opened[1] is opened[0]
    dialog=opened[1];dialog.ensure_section('Studio 与维护')
    buttons={button.text():button for button in dialog.pages.widget(1).findChildren(QPushButton)}
    buttons['清除记录'].click();buttons['重置布局'].click()
    assert calls==['library-2','layout-2']
    parent.deleteLater()


def test_second_entry_while_settings_are_open_constructs_nothing(app,monkeypatch):
    from PySide6.QtWidgets import QDialog
    from twobyteasr.app import application_settings as settings
    write_preferences({})
    parent=QWidget();inner=[]
    def reenter(dialog):
        inner.append(settings.open_application_settings(parent))
        return QDialog.DialogCode.Rejected
    opened=settings_exec(monkeypatch,reenter)
    assert not settings.open_application_settings(parent)
    assert inner==[False] and len(opened)==1
    assert parent._application_settings_dialog is None
    opened[0].hide();parent.deleteLater()


def test_category_built_after_showing_gets_control_widths_zoom_and_language(app,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QLabel
    from twobyteasr import i18n
    from twobyteasr.app import ui_zoom
    monkeypatch.setitem(ui_zoom._state,'percent',150);monkeypatch.setitem(ui_zoom._state,'touched',True)
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE','en')
    dialog=make_dialog(tmp_path)
    dialog.show();app.processEvents()
    dialog.ensure_section('存储与缓存')
    spin=dialog.storage_panel.policy_controls['budget_bytes'][0]
    assert spin.property('fieldWidth')=='numeric'
    assert dialog.pages.widget(2).property('_uiZoomApplied')==150
    dialog.ensure_section('关于')
    titles=[label.text() for label in dialog.pages.widget(6).findChildren(QLabel) if label.objectName()=='settingsRowTitle']
    assert 'Check for updates and remind me when the app opens' in titles
    dialog.hide();dialog.deleteLater()


def test_category_built_after_showing_matches_one_built_before_at_150_percent(app,tmp_path,monkeypatch):
    # Real app: a category opened after the window is shown looked different at
    # 150%: its combo box kept 36 px (classified after the window's sheet had
    # polished it) and shortcut rows listed later kept 100% margins.
    import time
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QPushButton
    from twobyteasr.app import ui_zoom
    monkeypatch.setitem(ui_zoom._state,'percent',150);monkeypatch.setitem(ui_zoom._state,'touched',True)
    def show(dialog):
        ui_zoom.window_shown(dialog)      # the theme manager's Show hook runs before showEvent
        dialog.show();app.processEvents()
    def controls(page):
        # Shortcut rows appear in batches (counts differ by timing); compared below by their margins.
        rows=page.findChild(QWidget,'shortcutScroll')
        found=[w for kind in (QPushButton,QComboBox,QAbstractSpinBox,QLineEdit) for w in page.findChildren(kind)
               if rows is None or not rows.isAncestorOf(w)]
        return sorted((type(w).__name__,w.objectName(),w.minimumWidth(),w.minimumHeight(),w.maximumHeight()) for w in found)
    def margins(row):
        m=row.layout().contentsMargins();return (m.left(),m.top(),m.right(),m.bottom())
    for label,index in (('存储与缓存',2),('快捷键',4),('外部 AI（MCP）',5)):
        late=make_dialog(tmp_path);show(late);late.ensure_section(label);app.processEvents()
        early=make_dialog(tmp_path);early.ensure_section(label);show(early)
        assert controls(late.pages.widget(index))==controls(early.pages.widget(index)),label
        if label=='快捷键':
            panel=late.shortcut_panel;deadline=time.monotonic()+5
            while not panel.construction_complete and time.monotonic()<deadline:
                QTest.qWait(10)
            rows=list(panel.rows.values())
            assert panel.construction_complete and margins(rows[-1])==margins(rows[0])
            assert panel.scope_filter.minimumHeight()==early.shortcut_panel.scope_filter.minimumHeight()
        late.hide();early.hide();late.deleteLater();early.deleteLater()


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
    canvas=MpvCanvas()
    canvas._media_attached=True
    canvas._timer.start(17);canvas._sync_timer.setInterval(150)
    canvas.set_navigation_visible(False)
    canvas.set_navigation_visible(False)
    assert not canvas._timer.isActive() and not canvas._sync_timer.isActive()
    canvas.set_navigation_visible(True)
    assert canvas._timer.isActive() and canvas._timer.interval()==17
    assert not canvas._sync_timer.isActive()
    canvas._timer.stop()
    canvas.deleteLater()


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


def test_studio_needed_before_its_queued_build_starts_is_built_once_and_opens_the_request(app, tmp_path, monkeypatch):
    """2026-10-25 (combined daily): open_studio_project queues the cooperative
    build until the loading page paints. Code that reads studio_page before
    that built Studio the old way, dropped the queued project and left the
    queued start to build a second page."""
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    built = []
    original = SubtitleStudioPage.__init__

    def counting(self, *args, **kwargs):
        built.append(kwargs.get('deferred_build', False))
        original(self, *args, **kwargs)

    monkeypatch.setattr(SubtitleStudioPage, '__init__', counting)
    opened = []
    monkeypatch.setattr(MainWindow, '_open_subtitle_studio', lambda self, path=None, **kw: opened.append(path))
    win = MainWindow([], legacy, object(), None)
    try:
        target = str(tmp_path / 'p.2byteproj')
        win.open_studio_project(target, source='canonical')
        assert built == [] and win.built_page('studio') is None    # queued, not started
        page = win.studio_page                                      # needed before the loading page painted
        win._start_studio_construction()                            # the queued start arrives late
        app.processEvents()
        assert built == [False] and win.studio_page is page
        assert opened == [target]
    finally:
        win.deleteLater()
        app.processEvents()
