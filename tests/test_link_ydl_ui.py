"""Link download A+B (2026-10-26): YDL GUI style window, Studio Ctrl+V quick card,
audio-only downloads, pause / resume."""
import json
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.media import link_choices as choices
from twobyteasr.media import link_download as ld
from twobyteasr.media.link_catalog import video_catalog
from twobyteasr.media.link_manifest import atomic_json
from twobyteasr.media.link_queue import DownloadQueue
from twobyteasr.media.link_tools import DownloadCancelled

VIDEO = "BaW_jenozKc"


def catalog(**extra):
    subtitles = {"en": [dict(ext="json3", url="https://youtube.com/api/timedtext?lang=en")],
                 "de": [dict(ext="json3", url="https://youtube.com/api/timedtext?lang=de")]}
    automatic = {"en": [dict(ext="json3", url="https://youtube.com/api/timedtext?lang=en&kind=asr")],
                 "ja": [dict(ext="vtt", url="https://youtube.com/api/timedtext?lang=en&kind=asr&tlang=ja")]}
    info = dict(id=VIDEO, title="Sample", duration=2538, language="en", uploader="Channel", upload_date="20261020",
        formats=[dict(format_id="137", vcodec="avc1.640028", acodec="none", height=1080, fps=60, ext="mp4", filesize=4_000_000),
                 dict(format_id="313", vcodec="vp9", acodec="none", height=2160, fps=60, ext="webm"),
                 dict(format_id="18", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360, fps=30, ext="mp4"),
                 dict(format_id="140", vcodec="none", acodec="mp4a.40.2", language="en", abr=129.5, ext="m4a"),
                 dict(format_id="251", vcodec="none", acodec="opus", language="en", abr=133, ext="webm")],
        subtitles=subtitles, automatic_captions=automatic)
    info.update(extra)
    return video_catalog(info)


# ------------------------------------------------------------------ choices
@pytest.mark.parametrize("text,expected", [
    ("https://youtu.be/BaW_jenozKc", "https://www.youtube.com/watch?v=BaW_jenozKc"),
    ("看这个 https://www.youtube.com/watch?v=BaW_jenozKc&list=PL1 很好", "https://www.youtube.com/watch?v=BaW_jenozKc"),
    ("youtube.com/shorts/BaW_jenozKc", "https://www.youtube.com/watch?v=BaW_jenozKc"),
    ("（https://youtu.be/BaW_jenozKc）", "https://www.youtube.com/watch?v=BaW_jenozKc"),
    ("https://www.bilibili.com/video/BV1xx411c7mD", "https://www.bilibili.com/video/BV1xx411c7mD?p=1"),
    ("普通的一句字幕文字", ""),
    ("", ""),
])
def test_find_video_link(text, expected):
    assert choices.find_video_link(text) == expected


def test_find_video_link_only_reads_the_start_of_a_huge_paste():
    huge = "x" * 5000 + " https://youtu.be/BaW_jenozKc"
    start = time.monotonic()
    assert choices.find_video_link(huge) == ""
    assert time.monotonic() - start < 0.5


def test_defaults_prefer_1080p_h264_original_manual_track_and_needed_audio():
    cat = catalog()
    default = choices.default_selection(cat)
    assert default["video_format"] == "137"            # not the 4K VP9 on top of the list
    assert default["audio_format"] == "140"            # the picture has no audio of its own
    manual_en = next(t for t in cat["tracks"] if t["source"] == "manual" and t["language"] == "en")
    assert default["track_ids"] == [manual_en["track_id"]] == [default["primary_track_id"]]
    audio = choices.default_selection(cat, mode="audio")
    assert audio["video_format"] == "" and audio["audio_format"] == "140" and audio["track_ids"] == []
    assert choices.default_selection(cat, mode="video")["track_ids"] == []


def test_chips_put_the_default_first_and_labels_are_readable():
    cat = catalog()
    chips = choices.chip_tracks(cat, ["ja"])
    assert chips[0]["track_id"] == choices.default_selection(cat)["primary_track_id"]
    assert any(t["source"] == "translated" and t["language"] == "ja" for t in chips)
    assert choices.track_label(chips[0]) == "英语 · 人工"
    assert choices.language_name("zh-Hans") == "中文（简体）" and choices.language_name("xx", "Other") == "Other"
    assert choices.video_label(choices.video_formats(cat)[1]).startswith("1080p · 60 fps · H.264")
    assert choices.audio_label(choices.audio_formats(cat)[0]).startswith("英语 · ")
    assert choices.duration_text(2538) == "42:18" and choices.duration_text(4000) == "1:06:40"
    assert choices.upload_date_text("20261020") == "2026-10-20"
    assert cat["uploader"] == "Channel"


# ------------------------------------------------------------- audio-only
def test_audio_task_needs_an_audio_format_and_drops_subtitles(tmp_path):
    cat = catalog()
    with pytest.raises(ValueError):
        ld.make_task(cat, str(tmp_path), mode="audio")
    task = ld.make_task(cat, str(tmp_path), mode="audio", video_format="137", audio_format="140",
                        track_ids=[cat["tracks"][0]["track_id"]], primary_track_id=cat["tracks"][0]["track_id"])
    assert task["mode"] == "audio" and task["video_format"] == "" and task["audio_format"] == "140"
    assert task["track_ids"] == [] and task["primary_track_id"] == ""


def test_audio_download_asks_ytdlp_for_the_audio_format_only(tmp_path, monkeypatch):
    cat = catalog()
    task = ld.make_task(cat, str(tmp_path), mode="audio", audio_format="140")
    root = Path(task["directory"])
    root.mkdir(parents=True)
    actual = root / (VIDEO + ".m4a")
    actual.write_bytes(b"audio")
    calls = []

    def run(tools, args, **kwargs):
        calls.append(args)
        return "2BYTE_FILE:" + json.dumps(str(actual)) + "\n", []
    monkeypatch.setattr(ld, "run_ytdlp", run)
    engine = ld.DownloadEngine(tools={"versions": {"yt_dlp": "offline"}})
    engine.analyze = lambda *a, **k: cat
    engine._subtitle_bytes = lambda *a, **k: pytest.fail("audio-only must not fetch subtitles")
    manifest = json.loads(Path(engine.download(task)).read_text("utf-8"))
    args = calls[0]
    assert args[args.index("--format") + 1] == "140"
    assert manifest["status"] == "completed" and manifest["media"]["path"] == actual.name
    assert manifest["audio_language"] == "en" and manifest["subtitles"] == []


# ------------------------------------------------------------ pause/resume
class SlowEngine:
    def __init__(self):
        self.started = threading.Event()
        self.runs = 0
        self.release = threading.Event()

    def download(self, task, *, cancel, notify, subtitles_only=False, **secrets):
        self.runs += 1
        self.started.set()
        while not self.release.is_set():
            if cancel():
                raise DownloadCancelled("已取消")
            notify(dict(stage="downloading", progress={"downloaded_bytes": 1, "total_bytes": 4}))
            time.sleep(.01)
        path = Path(task["directory"]) / "download.2byte-download.json"
        atomic_json(path, dict(version=1, task_id=task["task_id"], video_id=VIDEO, media=None, subtitles=[]))
        return str(path)


def wait_until(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.01)


def test_pause_keeps_the_task_and_resume_continues_it(tmp_path):
    engine = SlowEngine()
    queue = DownloadQueue(tmp_path / "queue.json", engine)
    queue._prepare_bundle = lambda path: {"manifest": {}, "media_path": ""}
    try:
        queue.add(dict(task_id="one", directory=str(tmp_path / "one"), state="queued", auto_import=True,
                       target={"project_id": "p"}))
        assert engine.started.wait(2)
        queue.pause("one")
        wait_until(lambda: queue.snapshots()[0]["state"] == "paused")
        task = queue.snapshots()[0]
        assert task["auto_import"] and task["target"] == {"project_id": "p"} and not task.get("error")
        engine.release.set()
        queue.resume("one")
        wait_until(lambda: queue.snapshots()[0]["state"] == "pending_import")
        assert engine.runs == 2 and queue.snapshots()[0]["auto_import"]
    finally:
        queue.close()


def test_cancel_wins_over_a_pending_pause_and_paused_tasks_can_be_cancelled(tmp_path):
    engine = SlowEngine()
    queue = DownloadQueue(tmp_path / "queue.json", engine)
    try:
        queue.add(dict(task_id="one", directory=str(tmp_path / "one"), state="queued"))
        queue.add(dict(task_id="two", directory=str(tmp_path / "two"), state="queued"))
        assert engine.started.wait(2)
        queue.pause("two")                      # still queued: paused at once
        assert queue.snapshots()[1]["state"] == "paused"
        queue.pause("one")
        queue.cancel("one")                     # the user changed their mind
        wait_until(lambda: queue.snapshots()[0]["state"] == "cancelled")
        queue.cancel("two")
        assert queue.snapshots()[1]["state"] == "cancelled"
        queue.clear_finished()
        assert queue.snapshots() == []
    finally:
        engine.release.set()
        queue.close()


# ------------------------------------------------------------------- Qt UI
class Engine:
    tools = None

    def __init__(self):
        self.calls = 0

    def analyze(self, url, **options):
        self.calls += 1
        time.sleep(.02)
        return catalog()


class FakePage(QWidget):
    project = None


@pytest.fixture
def controller(tmp_path):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.app.link_download_controller import LinkDownloadController
    host = QWidget()
    host.resize(1200, 800)
    page = FakePage(host)
    page.setObjectName("subtitleStudio")
    page.resize(1200, 800)
    engine = Engine()
    value = LinkDownloadController(host, engine=engine, storage=tmp_path / "queue.json")
    value.test_page = page
    value.test_engine = engine
    yield value
    value.shutdown()
    for widget in (value.dialog, value.card, value.popover, value.toast):
        if widget is not None:
            widget.close()
    host.close()
    app.processEvents()


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline
        QTest.qWait(20)


def test_window_audio_mode_and_pages(controller):
    controller.show()
    dialog = controller.dialog
    assert not dialog.parse_button.isEnabled()          # nothing pasted yet
    assert dialog.hero_head.isVisibleTo(dialog) and not dialog.result_card.isVisibleTo(dialog)
    dialog.set_catalog(catalog())
    assert not dialog.hero_head.isVisibleTo(dialog) and dialog.result_card.isVisibleTo(dialog)
    assert dialog.video_format.currentData() == "137"
    assert dialog._chips and all(chip.isChecked() == (tid in dialog.checked_tracks()) for tid, chip in dialog._chips.items())
    dialog.mode.setCurrentIndex(dialog.mode.findData("audio"))
    assert not dialog.video_format.isEnabled() and dialog.audio_format.isEnabled()
    assert dialog.audio_format.currentData() == "140" and not dialog.tracks.isEnabled()
    dialog.enqueue()
    task = controller.queue.snapshots()[-1]
    assert task["mode"] == "audio" and task["audio_format"] == "140" and task["track_ids"] == []
    for key in ("queue", "tools", "settings", "home"):
        dialog.show_page(key)
        assert dialog.pages.currentIndex() == ("home", "queue", "tools", "settings").index(key)
    dialog.show_page("queue")
    wait_for(lambda: task["task_id"] in dialog._cards)


def test_multisite_quick_card_shows_incomplete_subtitles(controller):
    controller.quick_paste(controller.test_page, "https://www.bilibili.com/video/BV1JZnr6TEMd?p=1")
    wait_for(lambda: controller.card.state == "ready")
    cat = catalog(subtitles={}, automatic={})
    cat["tracks"] = []
    cat["subtitle_status"] = "incomplete"
    controller.card.set_catalog(cat)
    assert controller.card.summary.text() == "字幕列表不完整"
    assert "Cookie" in controller.card.chip_layout.itemAt(0).widget().text()
    controller.show()
    controller.dialog.set_catalog(cat)
    assert "Cookie" in controller.dialog.subtitle_status.text()


def test_chip_and_full_list_stay_in_step(controller):
    controller.show()
    dialog = controller.dialog
    dialog.set_catalog(catalog())
    tid, chip = next(iter(dialog._chips.items()))
    chip.click()
    assert tid not in dialog.checked_tracks() and not chip.isChecked()
    for i in range(dialog.tracks.topLevelItemCount()):
        item = dialog.tracks.topLevelItem(i)
        if item.data(0, Qt.ItemDataRole.UserRole) == tid:
            item.setCheckState(0, Qt.CheckState.Checked)
    assert chip.isChecked() and dialog.primary.findData(tid) >= 0


def test_ctrl_v_opens_the_quick_card_only_for_links(controller):
    from twobyteasr.app import link_download_controller as module
    page = controller.test_page
    host = page.window()
    host._link_download_controller = controller
    clipboard = QApplication.clipboard()
    clipboard.setText("只是一句普通文字")
    assert module.paste_link(page) is False and controller.card is None
    clipboard.setText("https://youtu.be/BaW_jenozKc?si=share")
    assert module.paste_link(page) is True
    card = controller.card
    assert card.isVisible() and card.state == "parsing"
    wait_for(lambda: card.state == "ready")
    selection = card.selection()
    assert selection["mode"] == "both" and selection["video_format"] == "137" and selection["audio_format"] == "140"
    assert selection["track_ids"] == [choices.default_selection(card.catalog)["primary_track_id"]]
    QTest.keyClick(card, Qt.Key.Key_Return)
    task = controller.queue.snapshots()[-1]
    assert task["target"]["kind"] == "new" and task["auto_import"] and task["track_ids"] == selection["track_ids"]
    assert not card.isVisible()


def test_more_options_hands_the_parsed_video_over_without_parsing_again(controller):
    page = controller.test_page
    controller.quick_paste(page, "https://www.youtube.com/watch?v=BaW_jenozKc")
    card = controller.card
    wait_for(lambda: card.state == "ready")
    card.mode.setCurrentIndex(card.mode.findData("video"))
    calls = controller.test_engine.calls
    card._more()
    dialog = controller.dialog
    assert dialog.isVisible() and dialog.catalog is not None and controller.test_engine.calls == calls
    assert dialog.mode.currentData() == "video" and dialog.url.text().endswith(VIDEO)
    assert not card.isVisible()


def test_escape_closes_the_card_and_cancels_its_parse(controller):
    controller.quick_paste(controller.test_page, "https://www.youtube.com/watch?v=BaW_jenozKc")
    card = controller.card
    QTest.keyClick(card, Qt.Key.Key_Escape)
    assert not card.isVisible() and controller._analysis_token == ""


def test_task_cards_offer_the_right_actions():
    from twobyteasr.app.link_download_widgets import TaskCard
    names = lambda state, **extra: [a[0] for a in TaskCard.available_actions(dict(state=state, mode="both", **extra))]
    assert names("running") == ["pause", "cancel"]
    assert names("paused") == ["resume", "cancel"]
    assert names("pending_import") == ["import", "folder"]
    assert names("imported", import_result=dict(cue_count=3)) == ["edit", "ai", "folder"]
    assert names("imported", import_result=dict(cue_count=0)) == ["edit", "folder"]
    assert names("partial") == ["retry_subtitles", "import", "folder"]
    assert names("failed") == ["retry", "folder"]


def test_compact_card_shows_one_text_button(controller):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.app.link_download_widgets import TaskCard
    card = TaskCard("t", compact=True)
    card.update_task(dict(task_id="t", title="Video", state="imported", mode="both",
                          import_result=dict(cue_count=3)), {})
    texts = [w for w in card.findChildren(QPushButton) if w.text()]
    assert len(texts) == 1 and texts[0].text() == "进入编辑"
    assert card.state_text.text() == "已导入工程"


def test_capsule_follows_running_work():
    QApplication.instance() or QApplication([])
    from twobyteasr.app.link_quick_card import ProgressCapsule
    holder = QWidget()
    capsule = ProgressCapsule(holder)
    holder.show()
    capsule.set_state(0, None, False)
    assert not capsule.isVisible()
    capsule.set_state(1, .41, False)
    assert capsule.isVisible() and capsule.text() == "41%"
    capsule.set_state(0, None, True)
    assert capsule.isVisible() and capsule.property("tone") == "warn"
    holder.close()


def test_ctrl_v_is_a_contextual_studio_shortcut():
    from twobyteasr.studio import shortcut_registry
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    action = shortcut_registry.BY_ID["paste_link"]
    assert action.default == "Ctrl+V" and action.scope == "studio"
    assert "paste_link" in SubtitleStudioPage._CONTEXTUAL_SHORTCUTS
    values, conflicts = shortcut_registry.load_values({})
    assert values["paste_link"] == "Ctrl+V" and "paste_link" not in conflicts


def test_defaults_skip_drc_audio_and_prefer_separate_picture_streams():
    from twobyteasr.media.link_catalog import video_catalog
    cat = video_catalog(dict(id=VIDEO, title="Old", duration=19, formats=[
        dict(format_id="140-drc", vcodec="none", acodec="mp4a.40.2", ext="m4a", abr=129),
        dict(format_id="140", vcodec="none", acodec="mp4a.40.2", ext="m4a", abr=129),
        dict(format_id="18", vcodec="avc1.42001E", acodec="mp4a.40.2", height=240, ext="mp4"),
        dict(format_id="133", vcodec="avc1.4D400C", acodec="none", height=240, ext="mp4")],
        subtitles={}, automatic_captions={}))
    default = choices.default_selection(cat, mode="video")
    assert default["video_format"] == "133" and default["audio_format"] == "140"


def test_card_asks_when_several_uploaded_tracks_have_no_language_evidence(controller):
    from twobyteasr.media.link_catalog import video_catalog
    no_evidence = video_catalog(dict(id=VIDEO, title="Zoo", duration=19,
        formats=[dict(format_id="133", vcodec="avc1.4D400C", acodec="none", height=240, ext="mp4"),
                 dict(format_id="140", vcodec="none", acodec="mp4a.40.2", ext="m4a")],
        subtitles={"en": [dict(ext="json3", url="https://youtube.com/api/timedtext?lang=en")],
                   "de": [dict(ext="json3", url="https://youtube.com/api/timedtext?lang=de")]},
        automatic_captions={}))
    from twobyteasr.app.link_download_controller import save_link_preferences
    save_link_preferences({})   # an earlier download may have remembered a language
    controller.test_engine.analyze = lambda url, **options: no_evidence
    controller.quick_paste(controller.test_page, "https://www.youtube.com/watch?v=BaW_jenozKc")
    card = controller.card
    wait_for(lambda: card.state == "ready")
    assert card.selection()["track_ids"] == [] and card.status.isVisible() and card.status.text()
    tid, chip = next(iter(card._chips.items()))
    tall = card.frame.height()
    chip.click()
    assert not card.status.isVisible() and card.selection()["track_ids"] == [tid]
    QTest.qWait(80)   # the card fits again once the prompt row is gone
    assert card.frame.height() == card.frame.heightForWidth(card.frame.width()) < tall


# ------------------------------------------------- 2026-10-26 user feedback
def png_bytes():
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


class PreviewEngine(Engine):
    """A preview right away, the full result a moment later."""

    def __init__(self, delay=.4, thumbnail=""):
        super().__init__()
        self.delay = delay
        self.thumbnail = thumbnail

    def preview(self, url, *, cancel=None, proxy=""):
        return dict(video_id=VIDEO, title="Quick title", uploader="Quick channel", thumbnail=png_bytes())

    def analyze(self, url, **options):
        self.calls += 1
        time.sleep(self.delay)
        return catalog(thumbnail=self.thumbnail) if self.thumbnail else catalog()


def test_card_shows_title_and_cover_while_the_choices_load(controller):
    controller.engine = PreviewEngine()
    controller.quick_paste(controller.test_page, "https://www.youtube.com/watch?v=BaW_jenozKc")
    card = controller.card
    wait_for(lambda: card.title.text() == "Quick title")
    assert card.state == "parsing" and card.media_box.isVisible() and not card.body.isVisible()
    assert card.meta.text() == "Quick channel" and card.thumbnail
    wait_for(lambda: card.state == "ready")
    assert card.title.text() == "Sample" and card.thumbnail == png_bytes()   # the preview cover is reused


def test_choices_do_not_wait_for_the_cover(controller, monkeypatch):
    from twobyteasr.app import link_download_controller as module
    release = threading.Event()
    def slow_cover(url, **options):
        release.wait(5)
        return png_bytes()
    monkeypatch.setattr(module, "fetch_image", slow_cover)
    controller.engine = Engine()
    controller.engine.analyze = lambda url, **options: catalog(thumbnail="https://i.ytimg.com/vi/x/maxres.jpg")
    controller.quick_paste(controller.test_page, "https://www.youtube.com/watch?v=BaW_jenozKc")
    card = controller.card
    wait_for(lambda: card.state == "ready")
    assert not card.thumbnail
    release.set()
    wait_for(lambda: card.thumbnail == png_bytes())


def test_card_is_kept_on_its_screen(controller):
    controller.quick_paste(controller.test_page, "https://www.youtube.com/watch?v=BaW_jenozKc")
    card = controller.card
    from twobyteasr.app.link_quick_card import SHADOW
    area = (card.page.screen() or QApplication.primaryScreen()).availableGeometry()
    card._move_on_screen(area.right() + 3000, area.bottom() + 3000)
    assert card.geometry().right() - SHADOW <= area.right() + 1
    assert card.geometry().bottom() - SHADOW <= area.bottom() + 1


def test_window_height_follows_its_content(controller):
    controller.show()
    dialog = controller.dialog
    QTest.qWait(50)
    hero = dialog.height()
    dialog.set_catalog(catalog())
    QTest.qWait(80)
    page = dialog.pages.currentWidget()
    assert page.verticalScrollBar().maximum() == 0          # nothing hidden below
    assert dialog.height() > hero
    # The user's own height wins from then on.
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    QApplication.sendEvent(dialog, QResizeEvent(QSize(dialog.width(), 900), dialog.size()))
    assert dialog._user_sized is False                         # a programmatic event is not the user
