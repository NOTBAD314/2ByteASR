"""Actual export dialog failure, detail and retry in source or the full application EXE."""
import json
from pathlib import Path
import sys

def run(output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QTextEdit
    from twobyteasr.acceptance.subtitle_rescue_audit import fixture
    from twobyteasr.exports.studio_export_ui import SubtitleExportDialog
    from twobyteasr.exports import studio_subtitle_export as export
    app=QApplication.instance() or QApplication([])
    from twobyteasr.design.theme_manager import apply_application_theme
    apply_application_theme(app, "grape")
    p=fixture()
    for s in p.speakers:s.hidden=False
    p.media.path=str(output/"10月20日 (1).mp4")
    (output/"10月20日 (1).mp4").write_bytes(b"unused fixture")
    checks=[]
    def check(name,value):
        checks.append({"name":name,"passed":bool(value)})
        assert value,name
    dialog=SubtitleExportDialog(p,export_on_accept=True)
    for name,box in dialog.format_checks.items():box.setChecked(name=="srt")
    dialog.speaker_modes["per_speaker"].click()
    dialog.show();QTest.qWait(150)
    dialog.grab().save(str(output/"studio-ready.png"))
    original=export._atomic_text_write
    def corrupt(path,content):original(path,content.replace("上半句","损坏") if "S02" in path.name else content)
    export._atomic_text_write=corrupt
    try:QTest.mouseClick(dialog.export_button,Qt.MouseButton.LeftButton)
    finally:export._atomic_text_write=original
    QTest.qWait(150)  # queued relayout and scroll-to-error must be visible too
    check("failed_at_s02_18", "S02 第 18 条字幕" in dialog.warning.text())
    check("retry_and_details_available", dialog.error_details_button.isVisible() and dialog.export_button.isEnabled()
          and dialog.rect().contains(dialog.error_details_button.mapTo(dialog,dialog.error_details_button.rect().bottomRight()))
          and dialog.rect().contains(dialog.warning.mapTo(dialog,dialog.warning.rect().bottomRight())))
    check("nothing_published",not list(output.glob("*.srt")))
    dialog.grab().save(str(output/"studio-error.png"))
    (output/"layout.json").write_text(json.dumps({key:{"height":card.height(),"hint":card.sizeHint().height(),
        "min_height":card.minimumHeight(),"max_height":card.maximumHeight(),"own_style":card.styleSheet(),
        "layout_hint":card.layout().sizeHint().height(),"title_height":card.title.height(),
        "title_hint":card.title.sizeHint().height(),"note_height":card.note.height(),"note_hint":card.note.sizeHint().height()}
        for key,card in dialog.format_checks.items()},indent=2),encoding="utf-8")
    check("format_labels_not_clipped",all(card.title.height() >= card.title.sizeHint().height()
          and card.note.height() >= card.note.fontMetrics().height() for card in dialog.format_checks.values()))
    def inspect_detail():
        detail=app.activeModalWidget()
        check("detail_is_real_modal",isinstance(detail,QDialog) and detail is not dialog)
        text=detail.findChild(QTextEdit).toPlainText()
        check("detail_has_id_counts_and_comparisons",all(s in text for s in ("S02-18","expected_cue_count","timestamps_valid","unicode_valid","speaker_mapping_valid")))
        check("copy_is_available",any(b.text()=="复制详情" for b in detail.findChildren(QPushButton)))
        detail.grab().save(str(output/"studio-details.png"))
        detail.reject()
    QTimer.singleShot(100,inspect_detail)
    QTest.mouseClick(dialog.error_details_button,Qt.MouseButton.LeftButton)
    QTest.mouseClick(dialog.export_button,Qt.MouseButton.LeftButton)
    QTest.qWait(200)
    check("retry_publishes_all_four",dialog.pages.currentWidget() is dialog.done_page and len(dialog.artifacts)==4)
    check("all_80_cues",sum(a.cue_count for a in dialog.artifacts)==80)
    dialog.grab().save(str(output/"studio-success.png"))
    dialog.close();app.processEvents()
    (output/"result.json").write_text(json.dumps({"passed":len(checks),"failed":0,"checks":checks,"entry":"frozen" if getattr(sys,"frozen",False) else "source","executable":sys.executable},ensure_ascii=False,indent=2),encoding="utf-8")
    return 0


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import traceback
    def execute():
        code=1
        try:
            code=run(output)
        except Exception:
            (output/"result.json").write_text(json.dumps({"passed":0,"failed":1,"error":traceback.format_exc(),"entry":"frozen" if getattr(sys,"frozen",False) else "source","executable":sys.executable},ensure_ascii=False,indent=2),encoding="utf-8")
        QApplication.instance().exit(code)
    QTimer.singleShot(250,execute)
