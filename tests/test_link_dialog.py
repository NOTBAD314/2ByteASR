import json
import time
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
from twobyteasr.app.link_download_controller import LinkDownloadController
from twobyteasr.media.link_catalog import video_catalog


def catalog():
    return video_catalog(dict(id="BaW_jenozKc",title="标题 <b>保持原文</b>",duration=10,language="en",
        formats=[dict(format_id="v",vcodec="avc1",acodec="none",height=360,fps=30,ext="mp4"),
                 dict(format_id="a",vcodec="none",acodec="aac",language="en",ext="m4a")],
        subtitles={"en":[dict(ext="json3",url="https://youtube.com/api/timedtext?lang=en")]}))


class Engine:
    tools=None
    def analyze(self,url,**options):
        time.sleep(.03)
        return catalog()


@pytest.fixture
def dialog(tmp_path):
    app=QApplication.instance() or QApplication([])
    host=QWidget()
    controller=LinkDownloadController(host,engine=Engine(),storage=tmp_path/"queue.json")
    controller.show()
    yield controller.dialog
    controller.shutdown();controller.dialog.close();host.close();app.processEvents()


def test_parse_selection_and_no_model_gate(dialog):
    dialog.url.setText("https://youtu.be/BaW_jenozKc")
    dialog.parse()
    deadline=time.monotonic()+3
    while dialog.catalog is None:
        assert time.monotonic()<deadline
        QTest.qWait(30)
    assert dialog.add_button.isEnabled()
    assert dialog.checked_tracks()
    assert dialog.mode.currentData()=="both"
    assert dialog.primary.currentData()
    assert dialog.title.text().startswith("标题 <b>保持原文</b>")
    assert dialog.title.textFormat()==Qt.TextFormat.PlainText
    dialog.mode.setCurrentIndex(dialog.mode.findData("subtitles"))
    assert not dialog.video_format.isEnabled() and dialog.tracks.isEnabled()


def test_close_discards_late_analysis_without_destroyed_widget_callback(dialog):
    dialog.url.setText("https://youtu.be/BaW_jenozKc")
    dialog.parse()
    dialog.close()
    QTest.qWait(300)
    assert dialog.catalog is None
    assert not dialog.isVisible()


def test_current_target_requires_live_session(dialog):
    dialog.set_catalog(catalog())
    target=dialog.import_target()
    assert target["kind"]=="new" and target["project_id"]==""
    assert not target["confirmed_media"]
    assert dialog.cookie.text()=="" and not dialog.advanced.isChecked()
