import json
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.exports.export_affix import ExportAffixCombo, recent_affixes, HISTORY_LIMIT
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    settings.setValue('render/preferences_v1',json.dumps({'prefix':'[NOTBAD]','suffix':''}))
    monkeypatch.setattr('twobyteasr.exports.studio_export_ui.QSettings',lambda *_:settings)
    project=SubtitleProject(media=StudioMedia(str(tmp_path/'原视频.mp4'),duration_ms=18000),
        speakers=[StudioSpeaker('S1','同名'),StudioSpeaker('S2','同名')],cues=[
        StudioCue('a',10000,12000,'20 20','S1'),StudioCue('b',15000,17000,'二十','S2')])
    project.validate()
    widgets=[]
    def create():
        ui=StudioExportWorkspace(project,str(tmp_path/'preview.ass'),tmp_path/'demo.2byteproj')
        widgets.append(ui);app.processEvents();return ui
    yield create,settings,tmp_path,app
    for ui in widgets:ui.deleteLater()
    app.processEvents()


def test_confirmation_mru_empty_restart_exact_input_and_live_preview(workspace):
    create,settings,tmp,app=workspace;ui=create();p,s=ui.filename_prefix,ui.filename_suffix
    assert p.isEditable() and s.isEditable() and p.currentText()=='[NOTBAD]'
    assert p.history()==['[NOTBAD]'] and s.history()==[]
    p.clear();QTest.keyClicks(p.lineEdit(),'[NEW]')
    assert p.history()==['[NOTBAD]']
    assert ui.complete_name_preview.text()=='[NEW]原视频.mp4'
    QTest.keyClick(p.lineEdit(),Qt.Key_Return)
    assert p.history()==['[NEW]','[NOTBAD]']
    for value in ('_精剪','_完整版','_精剪',''):
        s.setEditText(value);QTest.keyClick(s.lineEdit(),Qt.Key_Return)
        assert ui.complete_name_preview.text()=='[NEW]原视频'+value+'.mp4'
    assert s.history()==['_精剪','_完整版']
    exact=' 【自定义】 a- '
    p.setEditText(exact);p.confirm();p.clear();p.confirm()
    ui.filename.setText('基础名.mp4.mp4');ui.filename.editingFinished.emit()
    saved=json.loads(settings.value('render/affixes_v1'))
    assert saved['prefix']==saved['suffix']=='' and saved['prefix_history'][0]==exact
    ui2=create()
    assert ui2.filename_prefix.currentText()==ui2.filename_suffix.currentText()==''
    assert ui2.filename.text()=='基础名.mp4.mp4'
    assert ui2.export_target().full_path.name=='基础名.mp4'
    ui2.filename_prefix.setCurrentIndex(ui2.filename_prefix.findText('[NOTBAD]'))
    ui2.filename_prefix.activated.emit(ui2.filename_prefix.currentIndex())
    ui2.extension.setCurrentIndex(ui2.extension.findData('mkv'))
    assert ui2.complete_name_preview.text()=='[NOTBAD]基础名.mkv'
    assert ui2.filename.text()=='基础名.mp4.mp4'
    assert len(recent_affixes([str(i) for i in range(100)],' newest '))==HISTORY_LIMIT


def test_subtitle_only_shared_name_unique_speakers_and_no_video_start(workspace,monkeypatch):
    create,settings,tmp,app=workspace;ui=create()
    ui.filename_prefix.setEditText('【自定义】 ')
    ui.filename_suffix.setEditText('_精剪')
    ui.subtitle_custom_directory.setText(str(tmp/'exports'))
    ui._subtitle_destination_changed('custom')
    ui.subtitle_speaker_modes['per_speaker'].setChecked(True)
    monkeypatch.setattr('twobyteasr.exports.studio_export_ui.run_render_job',lambda *_:pytest.fail('subtitle export started video'))
    QTest.mouseClick(ui.subtitle_export_button,Qt.LeftButton)
    paths=[item.path for item in ui._last_subtitle_artifacts]
    assert len(paths)==len(set(paths))==2
    assert all(path.name.startswith('【自定义】 原视频_精剪') and path.exists() for path in paths)
    assert not ui._running and ui._worker is None
    assert json.loads(settings.value('render/affixes_v1'))['suffix_history']==['_精剪']


def test_invalid_filename_still_sanitized(workspace):
    create,*_=workspace;ui=create()
    ui.filename_prefix.setEditText('[X]:?')
    ui.filename_suffix.setEditText(' /bad*')
    assert not any(c in ui.export_target().full_path.name for c in '<>:"/\\|?*')
