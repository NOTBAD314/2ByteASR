"""Recognition history opens from a persisted summary index (2026-10-12)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr import recognition_history as history  # noqa: E402
from twobyteasr.recognition_history import (  # noqa: E402
    RecognitionHistoryDetail,
    RecognitionHistoryIndex,
    RecognitionHistoryPage,
    parse_recognition_report,
)


def _app():
    return QApplication.instance() or QApplication([])


def _report(name: str, *, day: int = 14, status: str = "success", cues: int = 12) -> dict:
    return {
        "schema_version": 1,
        "status": status,
        "started_at": f"2026-08-{day:02d}T10:00:00+08:00",
        "finished_at": f"2026-08-{day:02d}T10:00:42+08:00",
        "media": {"name": name, "path": f"D:/media/{name}"},
        "settings": {"models": {"primary_asr_backend": "moss", "firered_asr_backend": "local",
                                "qwen_asr_backend": "local"},
                     "switches": {"use_ai_grouping": False}, "content_profile": {}},
        "stages": [{"index": 1, "label": "MOSS 全局转写", "status": "completed", "elapsed_seconds": 2.0}],
        "events": [], "review_items": [],
        "result": {"elapsed_seconds": 42.0, "cue_count": cues, "outputs": {}},
    }


def _write(folder: Path, stem: str, payload) -> Path:
    path = folder / f"{stem}_字幕任务报告.json"
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


def _wait(page, timeout=5.0):
    app = _app()
    end = time.monotonic() + timeout
    while page.background_busy() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not page.background_busy()


def _count_parses(monkeypatch):
    calls: list[Path] = []
    original = history.parse_recognition_report

    def counted(path):
        calls.append(Path(path))
        return original(path)
    monkeypatch.setattr(history, "parse_recognition_report", counted)
    return calls


def test_summary_index_is_persisted_and_reused_without_reparsing(tmp_path, monkeypatch):
    _app()
    reports, index_path = tmp_path / "reports", tmp_path / "cache" / "history.json"
    reports.mkdir()
    for number in range(3):
        _write(reports, f"任务{number}", _report(f"任务{number}.mp4", day=10 + number))
    calls = _count_parses(monkeypatch)
    first = RecognitionHistoryPage(reports, index_path=index_path)
    _wait(first)
    assert len(calls) == 3 and len(first.records) == 3
    assert index_path.is_file() and not index_path.is_relative_to(reports)
    assert not any(path.name.endswith(".tmp") for path in index_path.parent.iterdir())
    # The list keeps summaries only, never the report payloads.
    assert all(not hasattr(record, "payload") for record in first.records)

    calls.clear()
    second = RecognitionHistoryPage(reports, index_path=index_path)
    assert calls == []
    assert second.records == first.records
    first.deleteLater()
    second.deleteLater()


def test_only_changed_reports_are_parsed_and_outcome_version_invalidates(tmp_path, monkeypatch):
    _app()
    reports, index_path = tmp_path / "reports", tmp_path / "history.json"
    reports.mkdir()
    changed = _write(reports, "a", _report("a.mp4"))
    _write(reports, "b", _report("b.mp4", day=15))
    page = RecognitionHistoryPage(reports, index_path=index_path)
    _wait(page)
    calls = _count_parses(monkeypatch)
    _write(reports, "a", _report("a-renamed.mp4", cues=99))
    os.utime(changed, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
    page.refresh()
    assert calls == [changed]
    assert {record.media_name for record in page.records} == {"a-renamed.mp4", "b.mp4"}
    _wait(page)

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["outcome_version"] = -1
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    calls.clear()
    RecognitionHistoryPage(reports, index_path=index_path).deleteLater()
    assert len(calls) == 2
    page.deleteLater()


def test_corrupted_report_is_named_but_never_blocks_other_records(tmp_path, monkeypatch):
    _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports, "good", _report("good.mp4"))
    _write(reports, "bad", "{not json")
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    _wait(page)
    assert [record.media_name for record in page.records] == ["good.mp4"]
    assert "1 个文件无法读取" in page.summary.text()
    assert "bad_字幕任务报告.json" in page.summary.toolTip()
    calls = _count_parses(monkeypatch)
    page.refresh()
    assert calls == []  # an unchanged corrupted file is not parsed again
    page.deleteLater()


def test_large_or_many_changed_reports_are_read_off_the_gui_thread(tmp_path, monkeypatch):
    _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    for number in range(4):
        _write(reports, f"r{number}", _report(f"r{number}.mp4", day=10 + number))
    monkeypatch.setattr(history, "_INLINE_PARSE_BYTES", 0)
    import threading
    gui = threading.get_ident()
    threads: list[int] = []
    original = history.parse_recognition_report
    monkeypatch.setattr(history, "parse_recognition_report",
                        lambda path: (threads.append(threading.get_ident()), original(path))[1])
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    assert page.records == [] and page.background_busy()
    assert "正在读取 4 份报告" in page.summary.text()
    _wait(page)
    assert len(page.records) == 4 and threads and gui not in threads
    page.deleteLater()


def test_search_covers_every_record_not_only_built_cards(tmp_path):
    _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    for number in range(45):
        _write(reports, f"m{number:02d}", _report(f"素材{number:02d}.mp4", day=1 + number % 28, cues=number))
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    _wait(page)
    assert len(page.records) == 45
    assert len(page._cards) == page.PAGE_SIZE < 45
    assert page.more_button.isVisibleTo(page)
    oldest = page.records[-1].media_name
    assert oldest not in {card.record.media_name for card in page._cards}
    page.search.setText(oldest)
    assert [record.media_name for record in page._display] == [oldest]
    assert [card.record.media_name for card in page._cards] == [oldest]
    page.search.clear()
    page._show_more()
    assert len(page._cards) == 2 * page.PAGE_SIZE
    page.deleteLater()


def test_entry_check_adds_new_reports_and_ignores_superseded_listing(tmp_path):
    app = _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports, "one", _report("one.mp4"))
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    _wait(page)
    _write(reports, "two", _report("two.mp4", day=20, status="cancelled"))
    page._check_on_entry()
    page._generation += 1  # a newer reload owns the listing now
    _wait(page)
    assert [record.media_name for record in page.records] == ["one.mp4"]
    page.show()
    page._check_on_entry()
    _wait(page)
    app.processEvents()
    assert {record.media_name for record in page.records} == {"one.mp4", "two.mp4"}
    page.close()
    page.deleteLater()


def test_detail_builds_raw_json_only_when_expanded(tmp_path):
    app = _app()
    path = _write(tmp_path, "detail", _report("detail.mp4"))
    detail = RecognitionHistoryDetail(parse_recognition_report(path))
    assert "raw_view" not in vars(detail) and detail._raw_text is None
    detail.show()
    app.processEvents()
    detail.raw_button.click()
    app.processEvents()
    assert detail.raw_view.isVisible() and detail._raw_text
    assert json.loads(detail.raw_view.toPlainText())["media"]["name"] == "detail.mp4"
    detail.close()
    detail.deleteLater()


def test_show_detail_reads_only_the_selected_report_and_releases_the_dialog(tmp_path, monkeypatch):
    app = _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports, "a", _report("a.mp4"))
    target = _write(reports, "b", _report("b.mp4", day=20))
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    _wait(page)
    calls = _count_parses(monkeypatch)
    from twobyteasr.main_ui_dialogs import SpringDialog
    seen = []

    def fake_exec(dialog):
        app.processEvents()
        seen.append((dialog, dialog.findChild(RecognitionHistoryDetail)))
        return 0
    monkeypatch.setattr(SpringDialog, "exec", fake_exec)
    record = next(item for item in page.records if item.path == target)
    page.search.setText("b.mp4")
    page._show_detail(record)
    assert calls == [target]
    dialog, detail = seen[0]
    assert detail is not None and detail.record.path == target and "raw_view" not in vars(detail)
    # The list, its search and its cards are untouched by the detail.
    assert page.search.text() == "b.mp4" and [card.record.path for card in page._cards] == [target]
    from shiboken6 import isValid
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not isValid(dialog)

    # A large report is read in a background thread; the dialog shows first.
    monkeypatch.setattr(history, "_INLINE_DETAIL_BYTES", 0)
    seen.clear()

    def wait_exec(dialog):
        end = time.monotonic() + 5
        while dialog.findChild(RecognitionHistoryDetail) is None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        seen.append((dialog, dialog.findChild(RecognitionHistoryDetail)))
        return 0
    monkeypatch.setattr(SpringDialog, "exec", wait_exec)
    page._show_detail(record)
    assert seen[0][1] is not None and seen[0][1].record.path == target
    page.deleteLater()


def test_index_round_trips_summaries(tmp_path):
    path = _write(tmp_path, "x", _report("x.mp4"))
    summary = history.summarize_report(path)
    index = RecognitionHistoryIndex(tmp_path / "i.json")
    stat = path.stat()
    index.put(path, stat.st_mtime_ns, stat.st_size, summary, None)
    RecognitionHistoryIndex.write(index.path, index.payload({str(path)}))
    loaded = RecognitionHistoryIndex(tmp_path / "i.json")
    loaded.load()
    assert loaded.lookup(path, stat.st_mtime_ns, stat.st_size)[2] == summary
    assert loaded.lookup(path, stat.st_mtime_ns + 1, stat.st_size) is None


def test_detail_closed_before_its_report_arrives_drops_the_late_result(tmp_path, monkeypatch):
    """The reader thread never holds the dialog; a late result is ignored."""
    import threading
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    from twobyteasr.main_ui_dialogs import SpringDialog
    app = _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    target = _write(reports, "slow", _report("slow.mp4"))
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    _wait(page)
    monkeypatch.setattr(history, "_INLINE_DETAIL_BYTES", 0)
    release, started = threading.Event(), threading.Event()
    original = history.parse_recognition_report

    def slow_parse(path):
        started.set()
        release.wait(5)
        return original(path)
    monkeypatch.setattr(history, "parse_recognition_report", slow_parse)
    dialogs = []
    monkeypatch.setattr(SpringDialog, "exec", lambda dialog: dialogs.append(dialog) or 0)
    page._show_detail(page.records[0])
    assert started.wait(5) and page._detail_requests == {}
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not isValid(dialogs[0])
    release.set()
    end = time.monotonic() + 5
    while any(thread.name == "history-detail-reader" for thread in threading.enumerate()) and time.monotonic() < end:
        time.sleep(0.01)
    for _ in range(5):
        app.processEvents()
    assert page._detail_requests == {}
    assert target.is_file()
    page.deleteLater()


def test_repeated_threaded_detail_opens_release_every_dialog(tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from twobyteasr.main_ui_dialogs import SpringDialog
    app = _app()
    reports = tmp_path / "reports"
    reports.mkdir()
    _write(reports, "big", _report("big.mp4"))
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json")
    _wait(page)
    monkeypatch.setattr(history, "_INLINE_DETAIL_BYTES", 0)

    def wait_exec(dialog):
        end = time.monotonic() + 5
        while dialog.findChild(RecognitionHistoryDetail) is None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        assert dialog.findChild(RecognitionHistoryDetail) is not None
        return 0
    monkeypatch.setattr(SpringDialog, "exec", wait_exec)

    def settle():
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
    page._show_detail(page.records[0])
    settle()
    baseline = len(QApplication.allWidgets())
    for _ in range(15):
        page._show_detail(page.records[0])
        settle()
    assert len(QApplication.allWidgets()) <= baseline
    assert page._detail_requests == {}
    page.deleteLater()


def test_language_events_translate_each_newly_shown_subtree_once(monkeypatch):
    from twobyteasr import i18n
    from twobyteasr.i18n_widgets import install_language_events
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    app = _app()
    install_language_events()
    monkeypatch.setitem(i18n._TRANSLATIONS["en"], "识别记录", "Recognition history")
    monkeypatch.setattr(i18n, "current_language", lambda: "en")
    roots = []
    for _ in range(3):
        root = QWidget()
        layout = QVBoxLayout(root)
        inner = QWidget()
        QVBoxLayout(inner).addWidget(QLabel("识别记录"))
        layout.addWidget(inner)
        root.show()
        roots.append(root)
    for _ in range(5):
        app.processEvents()
    assert all(root.findChild(QLabel).text() == "Recognition history" for root in roots)
    for root in roots:
        root.close()
        root.deleteLater()
    app.processEvents()
