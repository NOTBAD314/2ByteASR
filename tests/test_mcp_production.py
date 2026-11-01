"""Production jobs use the real Qt bridge and preserve the legacy contracts."""
import asyncio
import json
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.local_mcp import mcp_common as common
from twobyteasr.local_mcp.mcp_bridge import BridgeError, McpBridge
from twobyteasr.local_mcp.production import ACTIVE, OPERATIONS, ProductionCore, error_info
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def service(tmp_path, application, monkeypatch):
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path / "profile"))
    project = SubtitleProject(media=StudioMedia("test.mp4", duration_ms=5000),
                              cues=[StudioCue("a", 0, 1000, "原始字幕")])
    window, page = QWidget(), QWidget()
    page.project = project
    page.session = SimpleNamespace(project_path=str(tmp_path / "test.2byteproj"))
    page.undo_stack = QUndoStack(page)
    window.built_page = lambda _name: page
    bridge = McpBridge(window)
    bridge.settings = dict(common.DEFAULTS, enabled=True, allow_edits=True, allow_export=True)
    core = ProductionCore(bridge, journal_path=tmp_path / "jobs.json")
    yield core, page, bridge
    core.stop("test")
    wait_until(lambda: not any(t.isRunning() for t in core._workers.values()))
    bridge.stop("test")
    page.close()
    window.close()


def wait_until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while not predicate():
        QApplication.instance().processEvents()
        time.sleep(.002)
        if time.monotonic() > end:
            raise TimeoutError("Qt job did not finish")
    QApplication.instance().processEvents()


def test_discovery_adds_exactly_thirteen_without_replacing_legacy_tools():
    from twobyteasr.local_mcp.mcp_stdio import build_server
    tools = asyncio.run(build_server().list_tools())
    names = [t.name for t in tools]
    assert len(names) == len(set(names)) == 31
    assert OPERATIONS <= set(names)
    schemas = {t.name: t.input_schema for t in tools}
    assert set(schemas["apply_plan"]["properties"]) == {"plan_id", "wait_seconds"}
    assert set(schemas["export_subtitles"]["properties"]) == {"formats", "layers", "name", "punctuation", "destination"}
    assert not any("authorization" in name or "capabilities" in name for name in names)
    assert all("batch_token" not in t.input_schema.get("properties", {}) for t in tools)


def test_late_result_detects_non_undo_content_change(service):
    core, page, bridge = service
    snap = core.snapshot(page, page.project)
    page.project.cues[0].text = "人工修改，没有经过撤销栈"
    assert bridge.revision == snap["revision"]
    with pytest.raises(BridgeError) as error:
        core.check_snapshot(snap)
    assert error.value.code == "stale_project"


def test_job_runs_off_thread_and_applies_on_gui_thread(service):
    core, page, _bridge = service
    gui = threading.get_ident()
    calls = []
    def work(token, progress):
        calls.append(("work", threading.get_ident()))
        progress({"done": 1, "total": 1})
        return {"value": 2}
    def apply(result, job):
        calls.append(("apply", threading.get_ident()))
        return result
    job = core.run_job("test", core.snapshot(page, page.project), work, apply)
    wait_until(lambda: core.jobs[job["job_id"]]["status"] not in ACTIVE)
    final = core.op_get_job(job["job_id"])
    assert final["status"] == "completed" and final["result"] == {"value": 2}
    assert calls[0][1] != gui and calls[1] == ("apply", gui)


def test_cancel_owns_one_task_and_waits_for_native_ack(service):
    core, page, _bridge = service
    entered = threading.Event()
    applied = []
    def work(token, progress):
        entered.set()
        while not token.is_cancelled:
            time.sleep(.002)
        token.raise_if_cancelled()
    job = core.run_job("test", core.snapshot(page, page.project), work,
                       lambda result, job: applied.append(result))
    wait_until(entered.is_set)
    assert core.op_cancel_job(job["job_id"])["status"] == "cancelling"
    wait_until(lambda: core.jobs[job["job_id"]]["status"] == "cancelled")
    assert not applied
    with pytest.raises(BridgeError) as error:
        core.op_cancel_job("a-native-task-not-owned-by-mcp")
    assert error.value.code == "unknown_job"


def test_shutdown_cancels_without_applying_worker_result(service):
    core, page, _bridge = service
    release = threading.Event()
    applied = []
    job = core.run_job("test", core.snapshot(page, page.project),
                       lambda token, progress: (release.wait(3), "result")[1],
                       lambda result, job: applied.append(result))
    core.stop("disabled")
    release.set()
    wait_until(lambda: core.jobs[job["job_id"]]["status"] == "cancelled")
    assert not applied


def test_cancelled_ai_receipt_survives_restart_without_applying(service):
    core, page, bridge = service
    released = threading.Event()
    applied = []
    native_result = object()
    def work(token, progress):
        released.wait(3)
        return native_result
    def summarize(result, job):
        assert result is native_result
        return {"api_status": "partial", "request_count": 1, "failed_cue_ids": ["a"]}
    started = core.run_job("sentence_refine", core.snapshot(page, page.project), work,
                           lambda result, job: applied.append(result), summarize_cancelled=summarize)
    core.op_cancel_job(started["job_id"])
    released.set()
    wait_until(lambda: core.jobs[started["job_id"]]["status"] == "cancelled")
    restored = ProductionCore(bridge, journal_path=core.journal_path)
    result = restored.op_get_job(started["job_id"])["result"]
    assert result["api_status"] == "partial" and result["request_count"] == 1
    assert result["failed_cue_ids"] == ["a"]
    assert result["cancellation"] == {"result_received": True, "applied": False, "retry_safe": False}
    assert not applied


def test_cancel_without_ai_result_does_not_claim_no_request(service):
    from twobyteasr.recognition.service import CancelledError
    core, page, bridge = service
    job = core.new_job("glossary_proofread", core.snapshot(page, page.project))
    core.fail_job(job, CancelledError("cancelled"))
    restored = ProductionCore(bridge, journal_path=core.journal_path)
    receipt = restored.op_get_job(job["job_id"])["result"]["cancellation"]
    assert receipt["request_state"] == "unknown" and receipt["retry_safe"] is False
    assert receipt["result_received"] is False


def test_restart_records_interrupted_without_replaying(service):
    core, page, bridge = service
    job = core.new_job("recognition", core.snapshot(page, page.project))
    restored = ProductionCore(bridge, journal_path=core.journal_path)
    state = restored.op_get_job(job["job_id"])
    assert state["status"] == "interrupted"
    assert not restored._workers and not restored.cancel_callbacks
    assert json.loads(core.journal_path.read_text("utf-8"))["jobs"][job["job_id"]]["status"] == "interrupted"


def test_page_preparation_continues_the_same_owned_job(service):
    core, page, _bridge = service
    prepared = core.new_job("create_media_project", {})
    started = core.run_job("create_media_project", core.snapshot(page, page.project),
                           lambda token, progress: {"created": True}, existing_job=prepared)
    assert started["job_id"] == prepared["job_id"] and len(core.jobs) == 1
    wait_until(lambda: prepared["status"] == "completed")
    with pytest.raises(BridgeError) as error:
        core.run_job("create_media_project", {}, lambda token, progress: {}, existing_job=dict(prepared))
    assert error.value.code == "invalid_job"


def test_busy_and_permissions_refuse_before_start(service):
    core, page, bridge = service
    snap = core.snapshot(page, page.project)
    core.new_job("recognition", snap)
    with pytest.raises(BridgeError) as error:
        core.new_job("second", snap)
    assert error.value.code == "busy"
    bridge.settings["allow_edits"] = False
    with pytest.raises(BridgeError) as error:
        core.require_project(page.project.project_id, bridge.revision)
    assert error.value.code == "not_permitted"


def test_native_text_workers_block_duplicate_paid_requests(service):
    core, page, _bridge = service
    page._refine_worker = SimpleNamespace(isRunning=lambda: True)
    with pytest.raises(BridgeError) as error:
        core.require_idle()
    assert error.value.code == "busy"
    page._refine_worker = None
    core.window.glossary_proofread_page = SimpleNamespace(checks_running=lambda: True)
    with pytest.raises(BridgeError) as error:
        core.require_idle()
    assert error.value.code == "busy"


def test_permission_revocation_cancels_active_work_and_invalidates_handoff(service):
    core, page, bridge = service
    bridge._production = core
    core.recognition_handoffs = {"previous-result": {"valid": True}}
    cancelled = []
    job = core.new_job("recognition", core.snapshot(page, page.project))
    core.cancel_callbacks[job["job_id"]] = lambda: cancelled.append(job["job_id"])
    bridge.apply_settings(dict(bridge.settings, allow_edits=False))
    assert cancelled == [job["job_id"]]
    assert job["status"] == "cancelling"
    assert not core.recognition_handoffs["previous-result"]["valid"]
    bridge.apply_settings(dict(bridge.settings, allow_edits=True))
    assert not core.recognition_handoffs["previous-result"]["valid"]


def test_named_pipe_dispatches_production_and_keeps_legacy_status(service):
    core, page, bridge = service
    bridge._production = core
    bridge.start()
    job = core.new_job("test", core.snapshot(page, page.project))
    core.finish_job(job, {"actual_output": "result"})
    box = {}
    def client():
        from twobyteasr.local_mcp.mcp_stdio import _call
        try:
            box["job"] = _call("get_job", job_id=job["job_id"])
            box["status"] = _call("status")
        except Exception as exc:
            box["error"] = exc
    thread = threading.Thread(target=client)
    thread.start()
    wait_until(lambda: not thread.is_alive())
    assert "error" not in box, box
    assert box["job"]["status"] == "completed"
    assert box["status"]["project"]["project_id"] == page.project.project_id
    assert "project_fingerprint" not in box["status"]["project"]


@pytest.mark.parametrize("error,code", [(TimeoutError("slow"), "timeout"),
    (RuntimeError("401 Unauthorized api_key=never-print-this"), "authentication_failed"),
    (RuntimeError("429 rate limit"), "rate_limited"),
    (RuntimeError("insufficient balance"), "insufficient_balance")])
def test_errors_are_distinct_and_secrets_redacted(error, code):
    info = error_info(error)
    assert info["code"] == code
    assert "never-print-this" not in info["message"]
