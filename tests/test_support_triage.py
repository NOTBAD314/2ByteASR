from datetime import datetime, timedelta, timezone

from twobyteasr.diagnostics.support_triage import (analyze, ago_text, legend, render_summary,
                                                     step_chips, step_headline)

BASE = datetime(2026, 10, 20, 17, 35, 0, tzinfo=timezone.utc)


class Journal:
    """Rows shaped like collect() output, at explicit second offsets."""
    def __init__(self):
        self.rows = []

    def add(self, at, event_name, **fields):
        row = dict(time=(BASE + timedelta(seconds=at)).isoformat(timespec="milliseconds"),
                   event_name=event_name, level=fields.pop("level", "INFO"), result=fields.pop("result", "observed"),
                   sequence=len(self.rows) + 1, session_id="session-test")
        row.update(fields)
        self.rows.append(row)
        return row

    def operation(self, at, action, op_id, duration=0.01, **end):
        self.add(at, "operation.start", action=action, operation_id=op_id, result="started")
        slow = duration > 0.25
        self.add(at + duration, "operation.end", action=action, operation_id=op_id, duration_ms=duration * 1000,
                 slow=slow, level="WARN" if slow else "INFO", result=end.pop("result", "completed"), **end)

    def data(self, marked_at):
        return dict(events=self.rows, sessions=[dict(session_id="session-test", status="running", platform="Windows-10")],
                    losses={}, missing=[], missing_count=0, scope="recent"), {"marked_at": (BASE + timedelta(seconds=marked_at)).isoformat()}


def stall(journal, at, duration, frames, **fields):
    for module in ("legacy", "studio.trace"):  # The watchdog records each stall twice.
        journal.add(at, "gui.stall", level="WARN" if module == "legacy" else "INFO", duration_ms=duration * 1000,
                    module=module, stacks=[{"samples": 3, "frames": frames}], **fields)


def example():
    j = Journal()
    j.add(0, "session.start", result="started")
    j.add(2.9, "startup.interactive", elapsed_ms=2900)
    for at in (3.2, 3.9, 4.6):
        j.add(at, "process.failure", level="ERROR", result="failed", purpose="ffmpeg encoder probe", exit_code=2981409195, child_pid=int(at * 10))
        j.add(at, "process.end", level="ERROR", result="failed", purpose="ffmpeg encoder probe", exit_code=2981409195, child_pid=int(at * 10))
    stall(j, 6.5, 1.9, ["threading.py:1:run", "studio_workspace.py:1289:build", "ui.py:1184:_build_lazy_page"])
    j.operation(7.0, "project.load", "op-load")
    j.add(7.4, "open.request")
    j.operation(7.5, "project.recover", "op-recover")
    j.operation(7.8, "cue.select", "op-auto-select")
    j.add(8.1, "open.finished", cue_count=24)
    j.add(8.15, "data.commit", action="transaction", operation_id="op-random-restore", before={}, after={})
    j.operation(10.0, "cue.select", "op-sel-1")
    j.operation(10.4, "cue.edit", "op-edit-1")
    j.operation(11.0, "cue.drag_commit", "op-drag-1")
    stall(j, 11.3, 0.47, ["studio_style_panel.py:972:_load_style_inspector", "studio_cue_controller.py:592:_select_cue_ui"])
    j.operation(14.0, "project.save", "op-save", duration=0.78)
    stall(j, 14.6, 0.61, ["studio_save.py:172:persist_with_progress"], operation_id="op-save")
    j.operation(15.0, "cue.merge_pair", "op-merge")
    j.add(15.05, "data.commit", action="SpliceCuesCommand._apply", operation_id="op-merge",
          before={"cue_count": 24, "valid_translation_sample_count": 2}, after={"cue_count": 23, "valid_translation_sample_count": 0})
    j.add(15.2, "data.commit", action="SetCueFieldsCommand._apply", operation_id="op-undo-random", before={}, after={})
    j.operation(16.0, "player.state", "op-state")
    j.operation(17.0, "cue.select", "op-sel-2")
    for code in ("parse_failure", "boundary_range", "parse_failure"):
        j.add(17.02, "ai.validation", level="ERROR", result="failed", task_id="task-ai", error_code=code,
              validator="parse_grouping_response", module="twobyteasr.subtitle_rules.grouping_contract")
    j.add(17.05, "ai.fallback", result="completed", task_id="task-ai", decision="rejected_invalid_candidates_used_local_source_boundaries")
    j.add(17.12, "thread.exception", level="ERROR", result="failed",
          exception={"chain": [{"type": "RuntimeError", "frames": [{"module": "worker.py", "line": 9, "function": "run"}]},
                               {"type": "ValueError", "frames": []}]})
    j.add(17.2, "process.start", purpose="mpv studio preview", child_operation_id="child-mpv")
    j.add(17.3, "problem.marked", report_id="report-test")
    return j


def test_steps_follow_what_the_person_did():
    data, report = example().data(17.3)
    result = analyze(data, report)
    names = [str(s.name) for s in result.steps]
    assert names[0] == "启动程序"
    assert names[1] == "打开工程"  # load + recover + the automatic select inside open.request..finished
    assert "编辑字幕 ×3" in names and "保存工程" in names and "合并字幕" in names
    assert "修改字幕" in names  # an undo/redo-like commit without an operation is its own step
    assert not any("player" in n for n in names)  # state notifications are not steps
    opened = result.steps[1]
    assert {"op-auto-select", "op-recover", "op-load"} <= opened.operation_ids
    undo = next(s for s in result.steps if str(s.name) == "修改字幕")
    assert "撤销" in str(undo.detail)


def test_issues_are_deduplicated_attributed_and_ranked():
    data, report = example().data(17.3)
    result = analyze(data, report)
    assert result.counts == {"act": 1, "check": 1, "stall": 3, "slow": 1, "auto": 1, "ignore": 1}
    stalls = [i for i in result.issues if i.kind == "stall"]
    assert sorted(round(i.duration_ms) for i in stalls) == [470, 610, 1900]  # each recorded twice, counted once
    first_open = next(i for i in stalls if round(i.duration_ms) == 1900)
    assert "第一次建立页面" in str(first_open.title) and "studio_workspace.py:1289 build" in first_open.dev
    save = next(s for s in result.steps if str(s.name) == "保存工程")
    assert {i.kind for i in save.issues} == {"stall", "slow"}
    assert all(str(i.relation) == "同一操作" for i in save.issues)
    merge = next(s for s in result.steps if str(s.name) == "合并字幕")
    assert str(merge.issues[0].title) == "有效译文从 2 条变成 0 条" and str(merge.issues[0].relation) == "同一操作"
    probes = next(i for i in result.issues if i.kind == "ignore")
    assert str(probes.title) == "硬件编码器探测 ×3" and probes.count == 3  # failure + end pair counted once
    ai = next(i for i in result.issues if i.kind == "auto")
    assert ai.count == 3 and "已改用本地断句" in str(ai.title) and str(ai.relation) == "同一任务"
    task = ai.step
    assert task.kind == "task" and str(task.name) == "AI 断句"
    error = next(i for i in result.issues if i.kind == "act")
    assert error.step is task and str(error.relation).startswith("之后 0.07 秒")
    assert "RuntimeError ← ValueError" in error.dev and "worker.py:9 run" in error.dev
    assert result.start_step is task
    assert [str(r) for r in result.running] == ["播放预览"]


def test_step_chips_headlines_and_relative_times():
    data, report = example().data(17.3)
    result = analyze(data, report)
    task = result.start_step
    assert [str(label) for _tone, label in step_chips(task)] == ["错误 1", "已处理 1"]
    assert str(step_headline(task)) == "这一步本身完成了，但之后 0.07 秒内出现 1 个错误"
    save = next(s for s in result.steps if str(s.name) == "保存工程")
    assert str(step_headline(save)) == "完成了，但用了 0.78 秒，期间画面卡住 1 次"
    assert str(ago_text(result, save.start)) == "−3.3 秒"
    assert [(tone, str(label), n) for tone, label, n in legend(result)][0] == ("danger", "需要处理", 1)


def test_log_rows_know_their_step_and_problem_flag():
    journal = example()
    data, report = journal.data(17.3)
    result = analyze(data, report)
    rows = journal.rows
    merge_commit = next(i for i, r in enumerate(rows) if r.get("operation_id") == "op-merge" and r["event_name"] == "data.commit")
    assert result.event_steps[merge_commit] == next(s.id for s in result.steps if str(s.name) == "合并字幕")
    assert result.event_problem[merge_commit]
    probe = next(i for i, r in enumerate(rows) if r.get("purpose") == "ffmpeg encoder probe")
    assert not result.event_problem[probe]  # ignorable rows stay out of "only problems"
    assert len(result.event_steps) == len(rows)


def test_summary_puts_the_conclusion_and_starting_point_first():
    data, report = example().data(17.3)
    result = analyze(data, report)
    text = render_summary(result, report_id="report-test", description="合并后译文不见了", version="0.8.1", scope="最近 15 分钟", event_count=len(data["events"]))
    lines = text.splitlines()
    conclusion = next(i for i, l in enumerate(lines) if l.startswith("【结论】"))
    start = next(i for i, l in enumerate(lines) if l.startswith("【从这里开始】"))
    trail = next(i for i, l in enumerate(lines) if l.startswith("【操作轨迹】"))
    assert conclusion < start < trail
    assert "需要处理 1 · 请核对 1 · 卡顿 3 次（最长 1.9 秒）" in lines[conclusion]
    assert "AI 断句" in lines[start] and "RuntimeError ← ValueError" in text
    assert "op-merge" in text and "有效译文从 2 条变成 0 条" in text
    assert "【可忽略】硬件编码器探测 ×3" in text and "【仍在执行】播放预览" in text


def test_quiet_range_says_so_and_points_to_detailed_recording():
    j = Journal()
    j.operation(1.0, "cue.select", "op-a")
    j.operation(2.0, "cue.edit", "op-b")
    data, report = j.data(3.0)
    result = analyze(data, report)
    assert result.start_step is None and result.counts.get("act", 0) == 0
    assert str(step_headline(result.steps[0])) == "没有发现问题"
    text = render_summary(result, report_id="report-quiet")
    assert "没有记录到错误" in text and "详细记录 10 分钟" in text


def test_previous_unclean_session_is_stated_without_guessing_a_cause():
    j = Journal()
    j.operation(1.0, "cue.select", "op-a")
    data, report = j.data(2.0)
    data["sessions"].append(dict(session_id="session-old", status="previous_not_cleanly_ended"))
    data["losses"] = {"critical_dropped": 2, "sampled_events": 4}
    result = analyze(data, report)
    notes = " ".join(str(n) for n in result.notes)
    assert "上次运行没有正常结束" in notes and "不能据此判定" in notes
    assert "critical_dropped" in notes and "4 条高频事件按规则抽样记录" in notes
