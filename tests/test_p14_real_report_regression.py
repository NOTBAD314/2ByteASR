import json
from collections import Counter
from pathlib import Path

import subtitle_core
from twobyteasr import output


FIXTURE = Path(__file__).parent / "fixtures" / "p14_real_task_report.json"


def _report():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_real_report_captures_the_pre_p14_structured_output_failure():
    report = _report()
    failed = [
        event for event in report["events"]
        if event.get("event") == "llm_request_failed"
        and event.get("stage") in {"polished", "grouped"}
    ]
    fallback = Counter(
        event.get("event") for event in report["events"]
        if event.get("event") in {"polishing_api_fallback", "grouping_api_fallback"}
    )

    assert Counter(event["stage"] for event in failed) == {
        "polished": 4,
        "grouped": 4,
    }
    assert fallback == {
        "polishing_api_fallback": 4,
        "grouping_api_fallback": 4,
    }
    assert all(event.get("max_tokens") == 1024 for event in failed)
    assert all(event.get("finish_reason") == "length" for event in failed)
    assert all(event.get("reasoning_content_present") is True for event in failed)
    assert all(event.get("message_content_length") == 0 for event in failed)
    assert all(event.get("structured_empty_retry") is False for event in failed)


def test_real_report_review_items_are_reclassified_without_losing_detail():
    items = _report()["review_items"]
    counts = Counter(subtitle_core.review_item_severity(item) for item in items)

    assert len(items) == 24
    assert counts == {"warning": 8, "review": 3, "info": 13}
    assert Counter(item["category"] for item in items) == {
        "Qwen骨架缺口": 10,
        "校对回退": 4,
        "断句回退": 4,
        "时间锚覆盖低": 3,
        "多模型争议": 2,
        "多模型文本冲突": 1,
    }


def test_real_report_contains_ten_qwen_supported_npc_lines_across_speakers():
    gaps = [
        item for item in _report()["review_items"]
        if item.get("category") == "Qwen骨架缺口"
    ]
    speakers = {
        speaker
        for item in gaps
        for speaker in ("S02", "S03", "S04", "S05", "S06", "S07")
        if speaker in item.get("detail", "")
    }

    assert len(gaps) == 10
    assert speakers == {"S02", "S03", "S05", "S06", "S07"}
    assert all("Qwen 文字支持 100%" in item["detail"] for item in gaps)
    assert all(item["text"] for item in gaps)


def test_user_summary_aggregates_fallbacks_and_keeps_all_json_items(capsys):
    subtitle_core.reset_review_items()
    for index in range(1, 5):
        subtitle_core.add_review_item(
            index,
            "校对回退",
            "fixture",
            f"batch {index}",
            priority=3,
            batch_index=index,
            batch_total=5,
        )
    subtitle_core.add_review_item(10, "多模型争议", "需要人工判断", "对白", priority=2)
    subtitle_core.add_review_item(11, "时间锚覆盖低", "已安全恢复", "对白", priority=2)

    items = output.print_review_summary()
    printed = capsys.readouterr().out

    assert len(items) == 6
    assert "AI 校对部分降级：4 / 5 个批次使用本地结果" in printed
    assert printed.count("AI 校对部分降级") == 1
    assert "[复核 · 多模型争议]" in printed
    assert "已安全恢复" not in printed
    assert "1 条 info/debug 诊断仅保留在 JSON 报告" in printed
    assert Counter(item["severity"] for item in items) == {
        "warning": 4,
        "review": 1,
        "info": 1,
    }
    subtitle_core.reset_review_items()


def test_split_batch_fallbacks_are_counted_per_original_batch(capsys):
    """2026-10-14 user report: a 2-hour Japanese job finished every stage, then
    failed with ``invalid literal for int() with base 10: '2.1.2'`` because a
    batch split twice (truncated model output) had fallen back."""
    from twobyteasr import reporting
    subtitle_core.reset_review_items()
    for index in ("2.1.2", "2.2", 4):
        subtitle_core.add_review_item(1, "校对回退", "fixture", f"batch {index}", priority=3,
                                      batch_index=index, batch_total=19)
    items = output.print_review_summary()
    assert "AI 校对部分降级：2 / 19 个批次使用本地结果" in capsys.readouterr().out
    summary = reporting._build_review_summary(items)
    assert summary[0]["message"] == "AI 校对部分降级：2 / 19 个批次使用本地结果。"
    subtitle_core.reset_review_items()
