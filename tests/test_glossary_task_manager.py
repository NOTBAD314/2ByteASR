"""VII 轮：全局任务管理器生命周期测试（伪引擎，无网络、无真实写入）。"""

from __future__ import annotations

import time

import pytest

pytest_qt = pytest.importorskip("PySide6.QtWidgets", reason="needs PySide6")

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.glossary import glossary_build as gbuild  # noqa: E402
from twobyteasr.glossary import glossary_task_manager as gtm  # noqa: E402
from twobyteasr.glossary.glossary_skill import SearchedTerm, TermDiff  # noqa: E402


class _Legacy:
    pass

def test_alias_identity_deduplicates_full_and_incremental(manager,monkeypatch):
    monkeypatch.setattr(manager,'_pump',lambda:None)
    manager.legacy.runtime_game_identity=lambda value:value.replace('：','').replace(':','').casefold()
    first,created=manager.submit('洛克王国：世界','full',{})
    second,duplicate=manager.submit('洛克王国:世界','incremental',{})
    assert created and not duplicate and second==first
    assert manager.get(first).game_id=='洛克王国世界'
    assert manager.pending_for_game('洛克王国:世界').task_id==first


def test_target_and_nested_ai_config_are_frozen_at_submit(manager, monkeypatch):
    monkeypatch.setattr(manager, '_pump', lambda: None)
    manager.legacy.resolve_glossary_identity = lambda name: 'library:stable'
    manager.legacy.glossary_display_name = lambda name: '原显示名'
    settings = {'models': {'polish_ai_service': 'grok_account', 'polish_model': 'grok-test'}}
    task_id, _ = manager.submit('原显示名', 'full', settings)
    settings['models']['polish_model'] = 'different-draft'
    assert manager.get(task_id).library_id == 'library:stable'
    assert manager._settings_by_task[task_id]['models']['polish_model'] == 'grok-test'


def test_upgrade_required_task_is_terminal_once(manager, app, monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('{"type":"error","message":"Internal error: API error (status 426 Upgrade Required): Your Grok CLI version (1.0.5) is outdated. Please update to version 1.0.13 or later"}')
    monkeypatch.setattr(gbuild, 'run_full_library_update', denied)
    task_id, _ = manager.submit('测试', 'full', {})
    assert _spin(app, lambda: manager.get(task_id).status == 'failed')
    task = manager.get(task_id)
    assert task.error_code == 'upgrade_required'
    assert '1.0.5' in task.error and '1.0.13' in task.error
    assert task.waiting_note == ''
    assert calls == [1]


def test_resume_shares_choices_only_with_same_task_family(manager,monkeypatch):
    monkeypatch.setattr(manager,'_pump',lambda:None)
    first,_=manager.submit('测试','full',{})
    task=manager.get(first);task.status='partial';task.review_choices.update({'甲':False,'乙':True})
    second,_=manager.submit('测试','full',{},resume_task_id=first)
    assert manager.get(second).review_choices is task.review_choices
    manager.get(second).status='partial'
    third,_=manager.submit('测试','full',{})
    assert manager.get(third).review_choices=={} and manager.get(third).review_choices is not task.review_choices


@pytest.fixture()
def app():
    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture(autouse=True)
def _isolate_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


@pytest.fixture()
def manager(app):
    gtm.GlossaryUpdateManager.reset()
    mgr = gtm.GlossaryUpdateManager(_Legacy())
    yield mgr
    mgr.shutdown(wait_ms=500)
    gtm.GlossaryUpdateManager.reset()


def _spin(app, condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    app.processEvents()
    return condition()


def _fake_result(count=3):
    diffs = [
        TermDiff(
            change_type="new",
            term=SearchedTerm(
                term=f"词{index}", category="角色", category_key="character",
                sources=({"url": f"https://a.b/{index}", "title": ""},),
                verification="page_verified",
            ),
        )
        for index in range(count)
    ]
    return {"diffs": diffs, "candidate_count": count, "mode": "full", "model": "m", "service": "s"}


def _stub_full(monkeypatch, *, slow=0.0, cancel_at=None):
    state = {"calls": 0}

    def fake(legacy, game, settings, *, report=None, cancel_check=None, resume=None,
             checkpoint_writer=None, on_candidates=None, on_event=None):
        state["calls"] += 1
        if slow:
            time.sleep(slow)
        if cancel_at is not None and cancel_check is not None and state["calls"] >= cancel_at:
            raise gtm.GlossarySearchError("cancelled", "已取消。")
        if report is not None:
            report("目录检索", "发现 2 个目录页", {})
            report("分批整理", "批次 1/2", {"batch_done": 1, "batch_total": 2, "candidates": 5})
        if on_candidates is not None:
            on_candidates([SearchedTerm(term="青衣", category="角色", category_key="character")])
        if checkpoint_writer is not None:
            checkpoint_writer({
                "game": game, "mode": "full", "names": [{"name": "青衣"}],
                "processed": ["青衣"], "candidates": [], "community_done": False,
            })
        return _fake_result()

    monkeypatch.setattr(gbuild, "run_full_library_update", fake)
    return state


def test_submit_runs_to_completion_and_attributions(manager, app, monkeypatch):
    _stub_full(monkeypatch)
    finished: list[tuple[str, str, int]] = []
    manager.task_finished.connect(lambda tid, game, result: finished.append((tid, game, len(result["diffs"]))))

    task_id, created = manager.submit("绝区零", "full", {})
    assert created
    assert _spin(app, lambda: bool(finished), timeout=5)
    assert finished[0][1] == "绝区零"  # 归属=任务自己的游戏
    task = manager.get(task_id)
    assert task.status == "finished"
    assert task.candidates == 3
    assert task.partial_candidates  # 快照已进入任务状态


def test_duplicate_submit_same_game_mode_dedupes(manager, app, monkeypatch):
    _stub_full(monkeypatch, slow=0.3)
    manager.submit("绝区零", "full", {})
    second_id, created = manager.submit("绝区零", "full", {})
    assert created is False
    assert second_id == manager.tasks()[0].task_id
    assert len(manager.tasks()) == 1
    assert _spin(app, lambda: manager.tasks()[0].status == "finished")


def test_queue_is_serial_and_attriutes_each_game(manager, app, monkeypatch):
    state = _stub_full(monkeypatch, slow=0.15)
    manager.submit("绝区零", "full", {})
    manager.submit("原神", "full", {})
    assert _spin(app, lambda: len(manager.tasks()) == 2 and all(
        t.status == "finished" for t in manager.tasks()), timeout=8)
    assert state["calls"] == 2
    # 并发=1：同一时刻至多一个 runner
    assert manager.running_task() is None or manager.running_task().status == "running"


def test_cancel_running_task_marks_cancelled_and_keeps_checkpoint(manager, app, monkeypatch, tmp_path):
    import threading as _threading

    gate = _threading.Event()
    cancelled_after = {"value": False}

    def fake(legacy, game, settings, *, report=None, cancel_check=None, resume=None,
             checkpoint_writer=None, on_candidates=None, on_event=None):
        if report is not None:
            report("目录检索", "…", {})
        if checkpoint_writer is not None:
            checkpoint_writer({
                "game": game, "mode": "full", "names": [{"name": "青衣"}],
                "processed": ["青衣"], "candidates": [], "community_done": False,
            })
        gate.wait(timeout=5)
        cancelled_after["value"] = bool(cancel_check and cancel_check())
        if cancelled_after["value"]:
            raise gtm.GlossarySearchError("cancelled", "已取消。")
        return _fake_result()

    monkeypatch.setattr(gbuild, "run_full_library_update", fake)
    failed: list[tuple[str, str, str]] = []
    manager.task_failed.connect(lambda tid, game, code, msg: failed.append((game, code, msg)))
    task_id, _ = manager.submit("绝区零", "full", {})
    assert _spin(app, lambda: manager.get(task_id).status == "running")
    manager.cancel(task_id)
    gate.set()
    assert _spin(app, lambda: bool(failed))
    assert failed[0][0] == "绝区零" and failed[0][1] == "cancelled"
    assert manager.get(task_id).status == "cancelled"
    assert gbuild.load_task_checkpoint(task_id) is not None  # 检查点保留 → 可继续
    assert manager.resumable_tasks("绝区零")


def test_cancel_queued_task_is_immediate(manager, app, monkeypatch):
    import threading as _threading

    gate = _threading.Event()

    def fake(legacy, game, settings, **kw):
        gate.wait(timeout=5)
        return _fake_result()

    monkeypatch.setattr(gbuild, "run_full_library_update", fake)
    first, _ = manager.submit("绝区零", "full", {})
    second, _ = manager.submit("原神", "full", {})
    manager.cancel(second)  # 排队任务立即取消
    assert manager.get(second).status == "cancelled"
    gate.set()
    assert _spin(app, lambda: manager.get(first).status == "finished")


def test_late_result_after_cancel_is_dropped(manager, app, monkeypatch):
    """迟到回调防护：任务已取消后到达的 finished_ok 不得翻转状态。"""
    task_id, _ = manager.submit("绝区零", "full", {})
    task = manager.get(task_id)
    task.status = "cancelled"  # 模拟已取消
    manager._on_finished_ok(task_id, "绝区零", _fake_result())
    assert task.status == "cancelled"
    assert task.result is None


def test_progress_updates_counters(manager, app):
    task_id, _ = manager.submit("绝区零", "full", {})
    manager._on_progress(task_id, "分批整理", "批次 2/5", 2, 5, 40)
    task = manager.get(task_id)
    assert (task.stage, task.batch_done, task.batch_total, task.candidates) == ("分批整理", 2, 5, 40)
    assert task.progress_line().startswith("分批整理")


def test_queued_cancel_message_and_remove(manager, app, monkeypatch):
    """排队即取消的任务：文案=已取消排队（无检查点语义）；终态任务可移除。"""
    import threading as _threading

    gate = _threading.Event()

    def fake(legacy, game, settings, **kw):
        gate.wait(timeout=5)
        return _fake_result()

    monkeypatch.setattr(gbuild, "run_full_library_update", fake)
    first, _ = manager.submit("绝区零", "full", {})     # 占住队列（阻塞在 gate）
    task_id, _ = manager.submit("原神", "full", {})     # 排队
    task = manager.get(task_id)
    assert task.status == "queued" and task.started is False
    # 排队任务不可移除（先取消）
    assert manager.remove(task_id) is False
    manager.cancel(task_id)
    assert task.status == "cancelled"
    assert "已取消排队" in task.progress_line()
    assert manager.remove(task_id) is True
    assert manager.get(task_id) is None
    gate.set()
    assert _spin(app, lambda: manager.get(first).status == "finished")


def test_pending_for_game_and_mode_labels(manager, app):
    task_id, _ = manager.submit("绝区零", "full", {})
    assert manager.pending_for_game("绝区零") is not None
    assert manager.pending_for_game("原神") is None
    assert manager.get(task_id).mode_label == "完整建库"


def test_waiting_anchor_shows_waited_seconds(manager, app):
    """等待锚点：progress_line 显示"已等待 N 秒"；业务事件清除锚点。"""
    task_id, _ = manager.submit("绝区零", "full", {})
    manager._on_progress(task_id, "目录检索", "请求已发出，等待返回：联网检索官方目录…", 0, 0, 0)
    task = manager.get(task_id)
    assert task.waiting_note.startswith("联网检索官方目录")
    line = task.progress_line()
    assert "已等待" in line and "联网检索官方目录" in line
    # 业务事件到达 → 锚点清除
    manager._on_progress(task_id, "名称提取", "分类枚举：新增 40 名", 0, 0, 40)
    assert manager.get(task_id).waiting_note == ""
    assert "已得 40 候选" in manager.get(task_id).progress_line()
    manager.cancel(task_id)
