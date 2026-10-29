import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QTextEdit

from twobyteasr.exports import studio_export_ui as ui
from twobyteasr.exports import studio_subtitle_export as export
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject

APP = QApplication.instance() or QApplication([])


def dialog_for(tmp_path, monkeypatch):
    settings=QSettings(str(tmp_path/"settings.ini"),QSettings.Format.IniFormat)
    monkeypatch.setattr(ui,"QSettings",lambda *_:settings)
    p=SubtitleProject(StudioMedia(str(tmp_path/"test.mp4"),duration_ms=10000),
                      cues=[StudioCue("cue-a",1000,1800,"上半句\n","S02"),StudioCue("cue-b",2000,2800,"第二句话","S02")])
    p.validate()
    d=ui.SubtitleExportDialog(p,export_on_accept=True)
    d.speaker_modes["per_speaker"].click()
    d.show()
    return d


def test_specific_error_details_and_copy_without_automatic_clipboard_change(tmp_path,monkeypatch):
    d=dialog_for(tmp_path,monkeypatch)
    write=export._atomic_text_write
    monkeypatch.setattr(export,"_atomic_text_write",lambda path,text:write(path,text.replace("第二句话","损坏")))
    d.export_button.click()
    assert "S02 第 2 条字幕" in d.warning.text() and d.error_details_button.isVisible()
    data=json.loads(d._error_details)
    assert data["first_mismatch"]["cue_id"]=="cue-b"
    assert data["expected_cue_count"]==data["cue_count"]==2
    assert data["timestamps_valid"] and data["speaker_mapping_valid"] and not data["unicode_valid"]
    captured=[]
    class Clipboard:
        def setText(self,text):captured.append(text)
    monkeypatch.setattr(ui.QApplication,"clipboard",staticmethod(lambda:Clipboard()))
    def inspect():
        modal=APP.activeModalWidget()
        assert modal.findChild(QTextEdit).toPlainText()==d._error_details
        next(b for b in modal.findChildren(QPushButton) if b.text()=="复制详情").click()
        modal.reject()
    assert not captured
    QTimer.singleShot(0,inspect)
    d.error_details_button.click()
    assert captured==[d._error_details]
    d.close()


def test_layer_success_followed_by_format_failure_is_explicit(tmp_path,monkeypatch):
    d=dialog_for(tmp_path,monkeypatch)
    monkeypatch.setattr(d,"_selected_layers",lambda:("original",))
    monkeypatch.setattr(d,"_selected_formats",lambda:frozenset({"srt","txt"}))
    def fail(*args,**kwargs):raise OSError("TXT 磁盘失败")
    monkeypatch.setattr(ui,"export_subtitle_artifacts",fail)
    d._run_export()
    assert d.pages.currentWidget() is d.setup_page and len(d.artifacts)==1
    assert d.artifacts[0].path.exists()
    assert d.artifacts[0].path.name in d.warning.text() and "未全部完成" in d.warning.text()
    assert "TXT 磁盘失败" in d._error_details
    d.close()
