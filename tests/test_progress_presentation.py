"""Recognition progress page (2026-10-08, visual refresh M12).

Determinate run bar over real steps, plain-language current action with live
facts, a readable record, the newest real text, honest cancel feedback, and
100% only once the save step completed.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.app import progress_model as model  # noqa: E402


def test_phase_ranges_follow_the_real_step_count():
    assert model.phase_ranges(11) == ({1, 2, 3, 4, 5, 6, 7}, {8}, {9, 10}, {11})
    # Without AI proofreading the run has 10 steps; step 8 is segmentation.
    assert model.phase_ranges(10) == ({1, 2, 3, 4, 5, 6, 7}, set(), {8, 9}, {10})
    assert model.phase_ranges(8) == ({1, 2, 3, 4, 5}, set(), {6, 7}, {8})


def test_hundred_percent_only_after_the_save_step():
    ten = set(range(1, 11))
    assert model.percent_text(model.overall_fraction(11, ten, {})) == "90%"
    # Real in-step counters never push an unsaved run to 100%.
    almost = model.overall_fraction(11, ten, {11: 0.99})
    assert almost < 1.0 and model.percent_text(almost) == "99%"
    assert model.percent_text(model.overall_fraction(11, set(range(1, 12)), {})) == "100%"
    # A failed review step the run continued past still counts as over.
    ended = model.ended_steps(set(range(1, 12)) - {6}, set(), {6}, 11)
    assert model.overall_fraction(11, ended, {}) == 1.0
    # A failed save step never counts.
    assert 11 not in model.ended_steps(set(range(1, 11)), set(), {11}, 11)
    # First of two media files fully saved is half, not done.
    assert model.overall_fraction(11, set(range(1, 12)), {}, 1, 2) == 0.5


def test_running_band_sits_after_the_finished_steps():
    # Steps 1 and 3 finished, 2 still running: the band is the third slot.
    assert model.active_spans(11, {2}, ended={1, 3}) == ((2 / 11, 3 / 11),)
    assert model.active_spans(11, set(), ended={1}) == ()


def test_stage_wording_is_plain_and_unknown_labels_pass_through():
    assert model.stage_record_name("统一 16k 音频采样时钟") == "准备音频"
    assert model.stage_action("FireRedVAD 人声安全检查") == "正在检测人声区间"
    assert model.moss_action("generation") == "MOSS 正在识别文本"
    assert model.stage_record_name("某个新阶段") == "某个新阶段"
    assert model.resource_mode("独立 Python 3.12 + GPU") == ("运行方式", "GPU 加速")
    assert model.resource_mode("grok_oauth/grok-4.7 · grok_cli+本地安全裁决") == ("服务", "grok_oauth · grok-4.7")


def _evidence(start, chars, done, total):
    stamps, t = [], 0.1
    for char, length in chars:
        stamps.append(dict(text=char, start=round(t, 2), end=round(t + length, 2)))
        t += length
    return dict(completed_chunks=done, total_chunks=total, processed_start=start,
                rows=[dict(text="".join(c for c, _ in chars), offset=start, timestamp=stamps)])


def test_evidence_preview_splits_on_absorbed_pauses_and_drops_overlap():
    # FireRed stamps English words as one token; a pause is absorbed into
    # the next character's duration.
    first = _evidence(0.0, [("今", .2), ("天", .2), ("打", .2), ("boss", .3), ("go", .2),
                           ("走", .9), ("吧", .2), ("队", .2), ("友", .2)], 1, 2)
    family, rows = model.preview_rows("asr_evidence_delta", first)
    assert family == "evidence"
    assert [row["text"] for row in rows] == ["今天打boss go", "走吧队友"]
    assert all(row["state"] == "provisional" for row in rows)
    # The next batch overlaps the end of the first; repeated lines are dropped.
    second_family, second = model.preview_rows(
        "asr_evidence_delta", _evidence(2.5, [("队", .2), ("友", .2), ("上", .9), ("啊", .2), ("冲", .2)], 2, 2))
    buffer = model.merge_preview(rows, second_family, family, second)
    assert [row["text"] for row in buffer] == ["今天打boss go", "走吧队友", "上啊冲"]


def test_proofread_results_replace_the_raw_preview_with_their_state():
    raw = model.preview_rows("asr_evidence_delta", _evidence(0.0, [("原", .2), ("文", .2)], 1, 1))[1]
    family, rows = model.preview_rows("terminology_polish_final", dict(
        cue_id=7, changed=True, details=dict(final_text="改后", response_state="success")))
    buffer = model.merge_preview(raw, family, "evidence", rows)
    assert buffer == [dict(start=None, cue=7, text="改后", state="polished_changed")]
    fallback = model.preview_rows("terminology_polish_final", dict(
        cue_id=8, changed=False, details=dict(final_text="原文", response_state="fallback")))[1]
    assert fallback[0]["state"] == "polish_fallback"
    assert model.PREVIEW_TAGS["provisional"][0] == "尚未校对"


# ------------------------------------------------------------------ window

def _window():
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow([], legacy, object(), None)


def _event(kind, **values):
    from twobyteasr.recognition.service import PipelineEvent
    return PipelineEvent(kind=kind, timestamp="", job_id="", **values)


def _stage(kind, index, label, resource="", seconds=0.0):
    return _event(kind, stage_index=index, stage_total=11, media_index=1, media_total=1,
                  label=label, resource=resource, elapsed_seconds=seconds)


def _moss(phase, tokens, elapsed, last):
    return _event("asr_worker_progress", payload=dict(backend="moss", phase=phase, generated_tokens=tokens,
                                                      elapsed_seconds=elapsed, last_activity_elapsed_seconds=last))


def test_moss_run_stays_determinate_and_names_the_action():
    import time
    from twobyteasr.app.progress_widgets import StageProgressBar
    win = _window()
    try:
        win._active_job_id = ""
        win.started_at = time.perf_counter()
        win._handle_event(_stage("stage_started", 1, "统一 16k 音频采样时钟", "CPU+磁盘缓存"))
        win._handle_event(_stage("stage_completed", 1, "统一 16k 音频采样时钟", seconds=0.3))
        win._handle_event(_stage("stage_started", 3, "FireRedVAD 人声安全检查", "CPU"))
        win._handle_event(_stage("stage_started", 2, "MOSS 全局说话人与粗时间转写", "独立 Python 3.12 + GPU"))
        win._handle_event(_stage("stage_completed", 3, "FireRedVAD 人声安全检查", seconds=6.4))
        win._handle_event(_event("asr_worker_started", payload=dict(backend="moss")))
        win._handle_event(_moss("generation", 200, 30.8, 30.8))
        assert isinstance(win.progress_bar, StageProgressBar)
        assert win.progress_bar.maximum() == 1000
        assert win.progress_percent.text() == "18%"
        assert win.progress_stage.text() == "MOSS 正在识别文本"
        facts = dict(win.stage_metrics.metrics())
        assert facts["累计输出"] == "200 tokens"
        # One sentence says what the step is doing (M14).
        assert win.progress_resource.text() == "正在进行整段音频识别"
        assert facts["最近输出"].endswith("秒前")
        assert win.progress_steps.text() == "2 / 11 步"
        # The device is context, not one of the headline facts (M13).
        assert "运行方式" not in facts and win.stage_device_label.text() == "GPU 加速"
        assert win.phase_cards[0].toolTip() == "进行中 · 2/7 步"
        assert "MOSS 正在整段识别" in win.recognition_preview.empty_text()
        # The record names steps plainly and ticks the running one.
        rows = [win.event_log.itemWidget(win.event_log.item(i)) for i in range(win.event_log.count())]
        assert [row.message_label.text() for row in rows if row._badge in {"完成", "运行中"}] == [
            "准备音频", "检测人声区间", "MOSS 识别文字与说话人"]
        # One clock (M13): a worker claiming its last output was 500 s ago
        # cannot read older than the step itself.
        win._handle_event(_moss("generation", 210, 500.0, 0.0))
        quiet = int(dict(win.stage_metrics.metrics())["最近输出"].split()[0])
        step = dict(win.stage_metrics.metrics())["已运行"]
        assert quiet <= int(step.split(":")[0]) * 60 + int(step.split(":")[1]) + 1
        # A finished MOSS phase says so instead of counting up "seconds ago".
        win._handle_event(_moss("completed", 1139, 56.0, 56.0))
        assert dict(win.stage_metrics.metrics())["最近输出"] == "已完成"
    finally:
        win.close()


def test_cancel_feedback_persists_and_the_end_closes_every_row():
    import time
    from twobyteasr.recognition.service import CancellationToken
    win = _window()
    try:
        win._active_job_id = ""
        win.started_at = time.perf_counter()
        win._handle_event(_stage("stage_started", 2, "MOSS 全局说话人与粗时间转写", "独立 Python 3.12 + GPU"))
        win._handle_event(_event("asr_worker_started", payload=dict(backend="moss")))
        win._handle_event(_moss("generation", 120, 20.0, 20.0))
        win.token = CancellationToken()
        win._cancel_run()
        assert win.cancel_run_button.text() == "正在取消…"
        # Late model events no longer overwrite the cancel state.
        win._handle_event(_moss("generation", 160, 21.0, 21.0))
        assert win.progress_stage.text() == "正在安全取消…"
        assert win.running_indicator.text() == "取消中"
        assert "已等待" in dict(win.stage_metrics.metrics())
        win._handle_event(_event("asr_worker_exited", payload=dict(backend="moss")))
        assert dict(win.stage_metrics.metrics())["模型子进程"] == "已停止"
        win._recognition_terminal = "cancelled"
        win._active_stages.clear()
        win._finish_progress_presentation()
        win._refresh_progress_cards()
        rows = [win.event_log.itemWidget(win.event_log.item(i)) for i in range(win.event_log.count())]
        assert not [row for row in rows if row._badge == "运行中"]
        assert win.running_indicator.text() == "已取消"
        assert win.cancel_run_button.text() == "安全取消"
        assert [card._state for card in win.phase_cards] == ["cancelled", "notrun", "notrun", "notrun"]
        assert win.progress_percent.text() != "100%"
    finally:
        win.token = None
        win.close()


def test_save_step_is_what_reaches_one_hundred_percent():
    import time
    win = _window()
    try:
        win._active_job_id = ""
        win.started_at = time.perf_counter()
        for index in range(1, 11):
            win._handle_event(_stage("stage_started", index, f"步骤{index}"))
            win._handle_event(_stage("stage_completed", index, f"步骤{index}", seconds=1.0))
        win._handle_event(_stage("stage_started", 11, "保存识别结果与工程", "磁盘"))
        assert win.progress_percent.text() == "90%"
        assert win.progress_stage.text() == "正在保存工程与报告"
        win._handle_event(_stage("stage_completed", 11, "保存识别结果与工程", seconds=0.4))
        assert win.progress_percent.text() == "100%"
        assert [card._state for card in win.phase_cards] == ["done"] * 4
    finally:
        win.close()
