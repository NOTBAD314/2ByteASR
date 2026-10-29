from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from twobyteasr.recognition.recognition_history import (  # noqa: E402
    RecognitionHistoryPage,
    RecognitionHistoryDetail,
    load_recognition_records,
    parse_recognition_report,
    redact_report_payload,
)


def _app():
    return QApplication.instance() or QApplication([])


def _report_payload():
    return {
        "schema_version": 1,
        "status": "success",
        "started_at": "2026-08-14T10:00:00+08:00",
        "finished_at": "2026-08-14T10:00:42+08:00",
        "media": {"name": "我的世界_01.mp4", "path": "D:/media/我的世界_01.mp4"},
        "settings": {
            "models": {
                "primary_asr_backend": "moss",
                "firered_asr_backend": "local",
                "qwen_asr_backend": "local",
                "group_model": "deepseek-v4-pro",
                "group_base_url": "https://api.deepseek.com",
            },
            "switches": {"use_ai_grouping": True},
            "content_profile": {
                "enabled_glossary_ids": ["minecraft", "creator-a", "common"],
                "domain_terms": True,
            },
        },
        "cache": {"hits": ["audio"], "writes": ["final"]},
        "stages": [
            {"index": 1, "label": "MOSS 全局转写", "status": "completed", "elapsed_seconds": 24.2},
            {"index": 2, "label": "FireRed 时间轴", "status": "completed", "elapsed_seconds": 8.1},
        ],
        "events": [],
        "review_items": [],
        "result": {
            "elapsed_seconds": 42.6,
            "cue_count": 128,
            "outputs": {"srt": "D:/media/我的世界_01.srt"},
        },
    }


def test_history_reads_existing_report_summary(tmp_path):
    path = tmp_path / "我的世界_01_字幕任务报告.json"
    path.write_text(json.dumps(_report_payload(), ensure_ascii=False), encoding="utf-8")
    record = parse_recognition_report(path)
    assert record.media_name == "我的世界_01.mp4"
    assert record.elapsed_seconds == 42.6
    assert (record.primary_model, record.timeline_model, record.review_model) == (
        "MOSS",
        "FireRed",
        "Qwen3-ASR",
    )
    assert record.ai_model == "deepseek-v4-pro"
    assert record.glossary_count == 3
    assert record.status_label == "完成"
    assert not record.has_anomaly


def test_success_with_review_and_info_remains_completed(tmp_path):
    payload = _report_payload()
    payload["review_items"] = [
        *(
            {"severity": "review", "category": "多模型争议", "message": f"复核 {index}"}
            for index in range(8)
        ),
        *(
            {"severity": "info", "category": "Qwen骨架缺口", "message": f"信息 {index}"}
            for index in range(4)
        ),
    ]
    payload["review_severity_counts"] = {
        "error": 0,
        "warning": 0,
        "review": 8,
        "info": 4,
        "debug": 0,
    }
    path = tmp_path / "排球卡车2_字幕任务报告.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    record = parse_recognition_report(path)

    assert record.status == "completed"
    assert record.status_label == "已完成 · 有待检查项"
    assert record.review_count == 8
    assert record.anomaly_count == 0
    assert not record.has_anomaly
    assert record.problems == ()


def test_warning_severity_drives_history_anomaly_semantics(tmp_path):
    payload = _report_payload()
    payload["review_items"] = [
        {"severity": "warning", "category": "校对回退", "message": "一批校对回退"},
        {"severity": "review", "category": "多模型争议", "message": "可人工复核"},
    ]
    path = tmp_path / "warning_字幕任务报告.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    record = parse_recognition_report(path)

    assert record.status == "partial"
    assert record.status_label == "部分完成"
    assert record.anomaly_count == 1
    assert record.review_count == 1
    assert record.has_anomaly


def test_history_redacts_nested_credentials_and_secret_values():
    redacted = redact_report_payload(
        {
            "api_key": "sk-super-secret-1234567890",
            "headers": {"Authorization": "Bearer abcdefghijklmnop"},
            "safe": {"token_count": 42, "url": "https://example.com"},
            "message": "request used sk-hidden-value-1234567890",
        }
    )
    rendered = json.dumps(redacted, ensure_ascii=False)
    assert "super-secret" not in rendered
    assert "abcdefghijklmnop" not in rendered
    assert "hidden-value" not in rendered
    assert redacted["safe"]["token_count"] == 42
    assert redacted["safe"]["url"] == "https://example.com"


def test_history_page_uses_exact_management_navigation(tmp_path):
    _app()
    path = tmp_path / "sample_字幕任务报告.json"
    path.write_text(json.dumps(_report_payload(), ensure_ascii=False), encoding="utf-8")
    page = RecognitionHistoryPage(tmp_path)
    assert len(page.records) == 1
    from twobyteasr.design.ui_navigation import WorkspaceNavigation

    navigation = page.findChild(WorkspaceNavigation)
    assert [button.text() for button in navigation.buttons.values()] == [
        "返回字幕识别",
        "模型工坊",
        "术语库",
        "识别记录",
    ]
    assert "设置" not in [button.text() for button in navigation.buttons.values()]
    page.deleteLater()


def test_history_loader_skips_bad_json_without_hiding_good_records(tmp_path):
    (tmp_path / "good_字幕任务报告.json").write_text(
        json.dumps(_report_payload(), ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "bad_字幕任务报告.json").write_text("{bad", encoding="utf-8")
    records, errors = load_recognition_records(tmp_path)
    assert len(records) == 1
    assert len(errors) == 1


def test_history_loader_reuses_cached_summary_until_file_signature_changes(
    tmp_path, monkeypatch
):
    path = tmp_path / "sample_字幕任务报告.json"
    path.write_text(json.dumps(_report_payload(), ensure_ascii=False), encoding="utf-8")
    cache = {}

    from twobyteasr.recognition import recognition_history

    original = recognition_history.parse_recognition_report
    parsed_paths = []

    def counted_parse(report_path):
        parsed_paths.append(Path(report_path))
        return original(report_path)

    monkeypatch.setattr(recognition_history, "parse_recognition_report", counted_parse)
    first, _ = load_recognition_records(tmp_path, cache=cache)
    second, _ = load_recognition_records(tmp_path, cache=cache)

    assert len(parsed_paths) == 1
    assert second[0] is first[0]

    changed = _report_payload()
    changed["media"]["name"] = "我的世界_02_changed.mp4"
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    third, _ = load_recognition_records(tmp_path, cache=cache)

    assert len(parsed_paths) == 2
    assert third[0].media_name == "我的世界_02_changed.mp4"


def test_history_page_reuses_existing_cards_and_only_adds_changed_report(tmp_path):
    _app()
    first_path = tmp_path / "first_字幕任务报告.json"
    first_path.write_text(
        json.dumps(_report_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    page = RecognitionHistoryPage(tmp_path)
    first_card = page._cards[0]

    page.refresh()
    assert page._cards == [first_card]

    second_payload = _report_payload()
    second_payload["finished_at"] = "2026-08-15T10:00:42+08:00"
    second_payload["media"]["name"] = "新增记录.mp4"
    (tmp_path / "second_字幕任务报告.json").write_text(
        json.dumps(second_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    page.refresh()

    assert len(page._cards) == 2
    assert first_card in page._cards
    assert {record.media_name for record in page.records} == {
        "我的世界_01.mp4",
        "新增记录.mp4",
    }
    page.deleteLater()


def test_history_detail_uses_product_summary_and_developer_json_view(tmp_path):
    app = _app()
    payload = _report_payload()
    payload["settings"]["models"]["qwen_asr_model"] = "Qwen/Qwen3-ASR-1.7B"
    payload["settings"]["models"]["polish_provider"] = "custom"
    payload["settings"]["models"]["polish_base_url"] = "https://api.deepseek.com"
    payload["settings"]["switches"]["dialogue_coverage_mode"] = "all_dialogue"
    payload["result"]["outputs"].update({
        "txt": "D:/private/result.txt",
        "speaker_outputs": [["S01", "D:/private/s1.srt", 60], ["S02", "D:/private/s2.srt", 68]],
    })
    payload["review_items"] = [
        {"severity": "review", "category": "多模型争议", "cue_id": index, "text": f"片段 {index}"}
        for index in range(8)
    ]
    path = tmp_path / "detail_字幕任务报告.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    detail = RecognitionHistoryDetail(parse_recognition_report(path))
    detail.resize(820, 900)
    detail.show()
    app.processEvents()

    labels = "\n".join(label.text() for label in detail.findChildren(QLabel))
    assert "MOSS-Transcribe-Diarize" in labels
    assert "FireRedASR2-AED" in labels
    assert "Qwen3-ASR 1.7B" in labels
    assert "DeepSeek · deepseek-v4-pro" in labels
    assert "多模型争议\n8 项问题" in labels
    assert "分轨 SRT · 2" in labels
    assert "D:/private" not in labels
    assert detail.stage_table.cellWidget(0, 1).findChild(QLabel).text() == "完成"

    detail.raw_button.click()
    app.processEvents()
    assert detail.raw_view.isVisible()
    assert detail.copy_button.isVisible()
    assert detail.raw_view.lineWrapMode() == detail.raw_view.LineWrapMode.NoWrap
    detail.copy_button.click()
    assert QApplication.clipboard().text() == detail.raw_text
    detail.raw_button.click()
    assert detail.raw_view.isHidden()
    detail.close()
    detail.deleteLater()


def test_large_history_json_can_be_saved_as_a_file(tmp_path, monkeypatch):
    # 2026-10-22: a 3.4 MB report pasted into a chat window froze it for 68 s.
    from PySide6.QtWidgets import QFileDialog
    from twobyteasr.recognition import recognition_history as history
    app = _app()
    path = tmp_path / "large_字幕任务报告.json"
    path.write_text(json.dumps(_report_payload(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(history, "LARGE_RAW_JSON_BYTES", 10)
    target = tmp_path / "saved.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "JSON (*.json)")))
    detail = RecognitionHistoryDetail(parse_recognition_report(path))
    detail.show()
    detail.raw_button.click()
    app.processEvents()
    assert detail.save_button.isVisible() and detail.raw_note.isVisible()
    assert "MB" in detail.raw_note.text()
    detail.save_button.click()
    assert target.read_text("utf-8") == detail.raw_text
    detail.raw_button.click()
    assert detail.save_button.isHidden() and detail.raw_note.isHidden()
    detail.close()
    detail.deleteLater()


def test_history_stage_table_fits_eleven_rows_without_nested_scroll(tmp_path):
    app = _app()
    payload = _report_payload()
    payload["stages"] = [
        {
            "index": index + 1,
            "label": f"阶段 {index + 1}",
            "status": "completed",
            "elapsed_seconds": index + 0.5,
        }
        for index in range(11)
    ]
    path = tmp_path / "eleven_stages_字幕任务报告.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    detail = RecognitionHistoryDetail(parse_recognition_report(path))
    detail.resize(820, 900)
    detail.show()
    app.processEvents()

    table = detail.stage_table
    required_height = (
        table.horizontalHeader().height()
        + sum(table.rowHeight(row) for row in range(table.rowCount()))
        + table.frameWidth() * 2
    )
    assert table.rowCount() == 11
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert table.height() >= required_height
    assert not table.verticalScrollBar().isVisible()
    detail.close()
    detail.deleteLater()


# ---------------------------------------------------------------- 多根扫描 / 历史修复 / 归档

def test_multi_root_scan_dedupes_copies_and_keeps_distinct_runs(tmp_path):
    stable = tmp_path / "stable-reports"
    legacy = tmp_path / "legacy-reports"
    stable.mkdir(); legacy.mkdir()
    payload = _report_payload()
    # 同一份报告被复制到两个根（跨重建存活场景）→ 只算一条
    (stable / "同一媒体_字幕任务报告.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (legacy / "同一媒体_字幕任务报告.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    # 同媒体真识别第二次（不同 started_at）→ 两条记录
    second = _report_payload()
    second["started_at"] = "2026-08-16T09:00:00+08:00"
    second["finished_at"] = "2026-08-16T09:01:00+08:00"
    (legacy / "同一媒体_20260816_字幕任务报告.json").write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")

    records, errors = load_recognition_records(stable, extra_roots=[legacy])
    assert errors == []
    assert len(records) == 2
    assert {record.payload.get("started_at") for record in records} == {
        "2026-08-14T10:00:00+08:00",
        "2026-08-16T09:00:00+08:00",
    }


def test_repair_imports_legacy_reports_without_touching_originals(tmp_path, monkeypatch):
    from twobyteasr.recognition import recognition_history as rh
    from twobyteasr.recognition.recognition_history import repair_recognition_history

    monkeypatch.setattr(rh, "discover_legacy_report_roots", lambda: [])
    from twobyteasr.recognition import reporting as _reporting

    monkeypatch.setattr(_reporting, "LEGACY_REPORT_ROOTS", ())

    stable = tmp_path / "stable-reports"
    legacy = tmp_path / "legacy-reports"
    legacy.mkdir()
    payload = _report_payload()
    (legacy / "旧任务A_字幕任务报告.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (legacy / "旧任务A_字幕任务报告.txt").write_text("report", encoding="utf-8")
    (legacy / "坏文件_字幕任务报告.json").write_text("{not json", encoding="utf-8")

    result = repair_recognition_history(stable, extra_roots=[legacy])
    assert result["found"] == 2
    assert result["imported"] == 1
    assert result["failed"] == 1
    assert result["failed_files"][0].startswith("坏文件_字幕任务报告.json")
    assert (stable / "旧任务A_字幕任务报告.json").exists()
    assert (stable / "旧任务A_字幕任务报告.txt").exists()
    assert (legacy / "旧任务A_字幕任务报告.json").exists()  # 原件保留
    # 二次修复：全部判重
    again = repair_recognition_history(stable, extra_roots=[legacy])
    assert again["imported"] == 0 and again["duplicates"] == 1


def test_same_media_new_run_archives_previous_report(tmp_path, monkeypatch):
    from twobyteasr.recognition import reporting

    monkeypatch.setattr(reporting, "REPORT_ROOT", tmp_path / "reports")
    clock = {"value": 0}

    def _fake_now():
        clock["value"] += 1
        return f"2026-09-18T15:02:{clock['value']:02d}+0800"

    monkeypatch.setattr(reporting, "_now", _fake_now)
    media = tmp_path / "素材.mp4"
    media.write_bytes(b"0")
    reporting.begin_media_report(str(media), {"cache_dir": ""}, {"models": {"qwen_asr_model": "Qwen3-ASR", "polish_model": "deepseek-v4-pro", "group_model": "deepseek-v4-pro"}, "switches": {}, "performance": {}})
    json_path, _text = reporting.finish_media_report("success", cue_count=1)
    first = json.loads(Path(json_path).read_text(encoding="utf-8"))

    # 同媒体第二次真实识别（started_at 不同）→ 旧报告归档改名，两条都保留
    reporting.begin_media_report(str(media), {"cache_dir": ""}, {"models": {"qwen_asr_model": "Qwen3-ASR", "polish_model": "deepseek-v4-pro", "group_model": "deepseek-v4-pro"}, "switches": {}, "performance": {}})
    json_path2, _text2 = reporting.finish_media_report("success", cue_count=2)
    second = json.loads(Path(json_path2).read_text(encoding="utf-8"))
    assert second["started_at"] != first["started_at"]
    names = sorted(path.name for path in (tmp_path / "reports").glob("*_字幕任务报告.json"))
    assert len(names) == 2  # 归档 + 最新
    records, _errors = load_recognition_records(tmp_path / "reports")
    assert len(records) == 2


def test_history_page_navigation_highlight_resets_on_restore(tmp_path):
    _app()
    page = RecognitionHistoryPage(tmp_path, extra_roots=[])
    # 模拟用户在其它页面点过"模型工坊"后回到识别记录
    page.nav.set_active("workshop")
    assert page.nav.buttons["history"].isChecked() is False
    page.restore_active_navigation()
    assert page.nav.buttons["history"].isChecked() is True
    assert page.nav.buttons["workshop"].isChecked() is False
    page.deleteLater()


def test_filtered_empty_state_differs_from_no_records(tmp_path):
    _app()
    page = RecognitionHistoryPage(tmp_path, extra_roots=[])
    assert page.empty.isVisibleTo(page)
    assert page.empty_title.text() == "还没有识别记录"
    payload = _report_payload()
    (tmp_path / "record_字幕任务报告.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    page.refresh()
    assert not page.empty.isVisibleTo(page)
    page.search.setText("绝不存在的关键词xyz")
    assert page.empty.isVisibleTo(page)
    assert page.empty_title.text() == "没有符合搜索条件的记录"
    assert not page.empty_start.isVisibleTo(page)
    page.deleteLater()


def test_history_new_outcome_labels_rebind_across_languages(tmp_path, monkeypatch):
    from twobyteasr import i18n
    from twobyteasr.i18n import apply_ui_language
    app = _app()
    payload = _report_payload()
    payload['result']['segment_count'] = 31
    payload['result']['cue_count'] = 32
    payload['polishing_summary'] = {'success_batches': 1, 'success_cues': 31, 'fallback_cues': 0,
                                    'term_context': {'accepted_edits': 6}}
    payload['terminology_summary'] = {'status': 'unsupported', 'reason': 'current provider has no retrieval', 'unverified_count': 31}
    source = tmp_path / 'localized_字幕任务报告.json'
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(i18n, 'current_language', lambda: 'en')
    translations = {'处理结果': 'Processing result', '核心处理': 'Core processing', '文字校对': 'Text proofreading',
        '处理记录': 'Input records', '实际接受修改': 'Accepted edits', '{count} 条处理记录': '{count} input records',
        '{count} 处文字修改': '{count} text edits', 'AI文字校对已完成': 'Text proofreading completed',
        '联网核验未执行（当前通道不支持）': 'Online verification not run (unsupported)'}
    for key, value in translations.items():
        monkeypatch.setitem(i18n._TRANSLATIONS['en'], key, value)
    detail = RecognitionHistoryDetail(parse_recognition_report(source))
    labels = '\n'.join(label.text() for label in detail.findChildren(QLabel))
    assert 'Core processing' in labels and '31 input records' in labels and '6 text edits' in labels
    assert 'Text proofreading completed' in labels and 'Online verification not run (unsupported)' in labels
    apply_ui_language(detail, 'zh')
    labels = '\n'.join(label.text() for label in detail.findChildren(QLabel))
    assert '核心处理' in labels and '31 条处理记录' in labels and '6 处文字修改' in labels
    assert 'Core processing' not in labels and 'input records' not in labels
    detail.deleteLater()
    app.processEvents()
