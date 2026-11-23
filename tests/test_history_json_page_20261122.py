"""识别记录：原始 JSON 单独成页、首页「识别记录」按钮、首次进入不先画空页（2026-11-22）。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.test_recognition_history import _app, _report_payload
from twobyteasr.recognition import history_json_page as json_page_module
from twobyteasr.recognition.history_json_page import HistoryJsonPage, JsonTree
from twobyteasr.recognition.recognition_history import (
    HistoryCard, RecognitionHistoryIndex, RecognitionHistoryPage, parse_recognition_report, summarize_report,
)


def _report(tmp_path, name="json.mp4", **extra):
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    payload = _report_payload()
    payload["media"]["name"] = name
    payload["settings"]["models"]["group_api_key"] = "sk-secret-value"
    payload.update(extra)
    path = reports / f"{name}_字幕任务报告.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    return reports, path


def _page(tmp_path, reports, **kwargs):
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json", **kwargs)
    page._roots = lambda: [reports]
    page.refresh()
    return page


def test_json_button_opens_its_own_page_and_back_returns_to_the_list(tmp_path):
    app = _app()
    reports, _path = _report(tmp_path)
    page = _page(tmp_path, reports)
    page.resize(1300, 860)
    page.show()
    app.processEvents()
    card = page.findChildren(HistoryCard)[0]
    card.raw_button.click()
    app.processEvents()
    json_page = page.json_page
    assert isinstance(json_page, HistoryJsonPage) and page.main_stack.currentWidget() is json_page
    assert json_page.title.text() == "json.mp4"
    data = json.loads(json_page.raw_text)
    assert data["media"]["name"] == "json.mp4"
    assert "sk-secret-value" not in json_page.raw_text            # still masked
    assert json_page.code.toPlainText() == json_page.raw_text
    assert json_page.tree.topLevelItemCount() == len(data)
    json_page.back_button.click()
    app.processEvents()
    assert page.main_stack.currentWidget() is page.list_view
    page.close()


def test_copy_and_save_from_the_json_page(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app = _app()
    reports, path = _report(tmp_path)
    target = tmp_path / "saved.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "JSON (*.json)")))
    page = HistoryJsonPage()
    page.show_record(parse_recognition_report(path))
    page.show()
    page.copy_button.click()
    assert QApplication.clipboard().text() == page.raw_text
    assert page.copy_button.property("done") is True and page.toast.text()
    page.save_button.click()
    assert target.read_text("utf-8") == page.raw_text
    page._clear_toast()
    assert page.copy_button.property("done") is False
    page.close()


def test_large_json_warns_to_save_a_file(tmp_path, monkeypatch):
    _app()
    _reports, path = _report(tmp_path)
    monkeypatch.setattr(json_page_module, "LARGE_JSON_BYTES", 10)
    page = HistoryJsonPage()
    page.show_record(parse_recognition_report(path))
    assert not page.note.isHidden() and "另存为" in page.note.text()


def test_search_finds_matches_and_switches_to_text(tmp_path):
    app = _app()
    _reports, path = _report(tmp_path)
    page = HistoryJsonPage()
    page.show_record(parse_recognition_report(path))
    page.show()
    assert page.views.currentWidget() is page.tree
    page.search.setText("moss")
    page._run_search()
    app.processEvents()
    assert page.views.currentWidget() is page.code
    assert len(page._matches) >= 1 and page.count_label.text().startswith("1 / ")
    page.find_next(1)
    assert len(page.code.extraSelections()) == len(page._matches)
    page.search.setText("no-such-text-anywhere")
    page._run_search()
    assert page._matches == [] and page.count_label.text()
    page.close()


def test_tree_opens_children_on_demand_and_bounds_long_lists(monkeypatch):
    _app()
    monkeypatch.setattr(json_page_module, "TREE_CHILD_LIMIT", 5)
    tree = JsonTree()
    tree.set_data({"items": list(range(12)), "nested": {"a": {"b": 1}}})
    nested = tree.topLevelItem(1)
    assert nested.childCount() == 1                     # opened: one level is shown at once
    inner = nested.child(0)
    assert inner.childCount() == 1 and inner.child(0).text(0) == ""  # placeholder until opened
    inner.setExpanded(True)
    assert inner.child(0).text(0) == "b"
    items = tree.topLevelItem(0)
    items.setExpanded(True)
    assert items.childCount() == 6 and "7" in items.child(5).text(0)   # 5 rows + 「还有 7 项…」
    tree._copy_item(items.child(5), 0)
    assert items.childCount() == 11 and "2" in items.child(10).text(0)   # 10 rows + 「还有 2 项…」


def test_detail_window_json_button_hands_over_to_the_page(tmp_path):
    from twobyteasr.recognition.recognition_history import RecognitionHistoryDetail
    _app()
    _reports, path = _report(tmp_path)
    detail = RecognitionHistoryDetail(parse_recognition_report(path))
    seen = []
    detail.raw_handler = seen.append
    detail.raw_button.click()
    assert seen and seen[0].media_name == "json.mp4" and "raw_view" not in vars(detail)


def test_first_visit_draws_records_from_the_index_at_once(tmp_path):
    """The page switch takes the first picture at once: it must already show the records."""
    _app()
    reports, path = _report(tmp_path)
    index = RecognitionHistoryIndex(tmp_path / "index.json")
    stat = path.stat()
    index.put(path, stat.st_mtime_ns, stat.st_size, summarize_report(path), None)
    RecognitionHistoryIndex.write(index.path, index.payload({str(path)}))
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "index.json", async_scan=True)
    assert [record.media_name for record in page.records] == ["json.mp4"]
    assert page.empty.isHidden()


def test_first_visit_without_index_says_it_is_reading_not_empty(tmp_path):
    _app()
    reports, _path = _report(tmp_path)
    page = RecognitionHistoryPage(reports, index_path=tmp_path / "missing" / "index.json", async_scan=True)
    if page._first_scan_running():
        assert "正在读取" in page.empty_title.text() and page.empty_start.isHidden()


def test_home_header_has_a_history_button_left_of_the_workshop_in_one_slot():
    """2026-11-23 (user): 识别记录 and 模型工坊 swap places; they share one slot with 返回字幕识别."""
    from twobyteasr.app import ui
    source = open(ui.__file__, encoding="utf-8").read()
    history = source.index("pair_row.addWidget(self.recognition_history_button)")
    workshop = source.index("pair_row.addWidget(self.model_workshop_button)")
    back = source.index("slot.addWidget(self.return_recognition_button)")
    assert history < workshop < back
    assert 'install_themed_icon(self.recognition_history_button, "fa5s.history", "accent")' in source
    assert "self.header_nav_stack.setCurrentWidget(self.return_recognition_button if workspace else self.header_nav_pair)" in source
    assert '(self.recognition_history_button, "识别记录")' in source
