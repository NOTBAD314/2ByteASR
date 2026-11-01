"""Job ownership and late-result guards for the independent production tools.

The legacy bridge keeps its approval plans. This module only dispatches its
explicit production operations, using the same access settings and GUI thread.
"""
from __future__ import annotations

import contextvars
import copy
import json
import os
import re
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from . import mcp_common as common
from .mcp_bridge import BridgeError

PROTOCOL = "native-production/1"
OPERATIONS = frozenset({
    "create_media_project", "open_project", "save_project", "start_recognition",
    "start_glossary_proofread", "start_sentence_refine", "cleanup_stutter",
    "detect_speech_pauses", "apply_pause_cuts", "export_video",
    "get_review_summary", "get_job", "cancel_job",
})
ACTIVE = frozenset({"queued", "running", "cancelling"})
DEFERRED = object()


def safe_message(value) -> str:
    """Keep diagnostics useful without echoing credentials in provider errors."""
    text = str(value)
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access_token|token|secret)[\s\"']*[:=][\s\"']*)[^\s\"'&,;]+",
                  r"\1[redacted]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{10,}", "[redacted]", text)
    return text[:2000]


def error_info(exc) -> dict:
    from ..recognition.service import CancelledError
    message = safe_message(exc)
    if isinstance(exc, BridgeError):
        code = exc.code
    elif isinstance(exc, CancelledError):
        code = "cancelled"
    elif isinstance(exc, (TimeoutError,)):
        code = "timeout"
    else:
        lower = message.lower()
        if any(word in lower for word in ("unauthorized", "authentication", "401", "403")):
            code = "authentication_failed"
        elif any(word in lower for word in ("insufficient_quota", "insufficient balance", "余额不足")):
            code = "insufficient_balance"
        elif any(word in lower for word in ("429", "rate limit", "限流")):
            code = "rate_limited"
        elif "timeout" in lower or "timed out" in lower:
            code = "timeout"
        elif isinstance(exc, ConnectionError):
            code = "network_error"
        else:
            code = "execution_failed"
    return {"code": code, "message": message}


class _JobThread(QThread):
    result_ready = Signal(str, object)
    failed = Signal(str, object)
    progress_changed = Signal(str, object)

    def __init__(self, job_id, work, token, parent):
        super().__init__(parent)
        self.job_id, self.work, self.token = job_id, work, token
        self.context = contextvars.copy_context()

    def run(self):
        try:
            self.token.raise_if_cancelled()
            result = self.context.run(self.work, self.token,
                                      lambda value: self.progress_changed.emit(self.job_id, value))
            self.result_ready.emit(self.job_id, result)
        except Exception as exc:  # delivered to the GUI, never silently retried
            self.failed.emit(self.job_id, exc)


class ProductionCore(QObject):
    def __init__(self, bridge, *, journal_path=None):
        super().__init__(bridge)
        self.bridge, self.window = bridge, bridge.window
        self.jobs = {}
        self.job_payloads = {}
        self.cancel_callbacks = {}
        self._workers = {}
        self._apply_callbacks = {}
        self._cancel_summaries = {}
        self._tokens = {}
        self._closed = False
        self.journal_path = Path(journal_path or common.settings_root() / "mcp" / "production-jobs.json")
        self._load_jobs()

    def _load_jobs(self):
        if not self.journal_path.exists():
            return
        try:
            payload = json.loads(self.journal_path.read_text(encoding="utf-8"))
            if payload.get("protocol") != PROTOCOL or not isinstance(payload.get("jobs"), dict):
                raise ValueError("unsupported job journal")
            self.jobs = payload["jobs"]
            changed = False
            for job in self.jobs.values():
                if job.get("status") in ACTIVE:
                    job.update(status="interrupted", message="程序已重启；先核对原生结果，不自动重新执行。",
                               error={"code": "interrupted", "message": "原任务结果需要核对"})
                    changed = True
                    if job.get("kind") in ("glossary_proofread", "sentence_refine"):
                        job.setdefault("result", {}).setdefault("cancellation", {
                            "request_state": "unknown", "result_received": False,
                            "applied": False, "retry_safe": False})
            if changed:
                self._persist()
        except (OSError, ValueError, TypeError) as exc:
            raise BridgeError("job_history_unavailable", "无法读取制作任务记录，原文件保留，请检查：" + str(self.journal_path)) from exc

    def _persist(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal_path.with_name(self.journal_path.name + ".tmp")
        temporary.write_text(json.dumps({"protocol": PROTOCOL, "jobs": self.jobs},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.journal_path)

    def require_access(self, permission=None):
        if self._closed or not self.bridge.settings.get("enabled"):
            raise BridgeError("unauthorized", "MCP 访问未开启或已撤销；请查看应用设置 → 外部 AI（MCP）。")
        if permission and not self.bridge.settings.get(permission):
            raise BridgeError("not_permitted", f"应用设置 → 外部 AI（MCP）未允许 {permission}。")

    def require_idle(self, exclude_job_id=None):
        if any(job.get("status") in ACTIVE and job_id != exclude_job_id for job_id, job in self.jobs.items()):
            raise BridgeError("busy", "已有 MCP 制作任务运行中；请先查询或取消原任务。")
        if getattr(self.window, "_run_in_progress", False):
            raise BridgeError("busy", "原生识别任务正在运行。")
        review = getattr(self.window, "glossary_proofread_page", None)
        if review is not None and callable(getattr(review, "checks_running", None)) and review.checks_running():
            raise BridgeError("busy", "原生校对页正在检查，请等待当前任务结束。")
        for owner in (self.window, self.bridge._page(), review):
            if owner is None:
                continue
            for name in ("worker", "_worker", "pipeline_worker", "_refine_worker", "_glossary_worker"):
                worker = getattr(owner, name, None)
                running = getattr(worker, "isRunning", None)
                if callable(running) and running():
                    raise BridgeError("busy", "原生任务正在运行；请等待当前任务结束。")

    def require_project(self, project_id, revision, permission="allow_edits", idle=True):
        self.require_access(permission)
        page, project = self.bridge._project()
        if not project_id or project.project_id != project_id:
            raise BridgeError("wrong_project", "当前工程与请求不一致。")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision != self.bridge.revision:
            raise BridgeError("stale_revision", "工程已变化，请重新读取当前工程状态。")
        if idle:
            self.require_idle()
        return page, project

    def snapshot(self, page, project):
        from ..recognition.recognition_input import project_content_revision
        return {"project_id": project.project_id, "revision": self.bridge.revision,
                "project_path": str(getattr(page.session, "project_path", "") or ""),
                "project_fingerprint": project_content_revision(project.to_dict())}

    def check_snapshot(self, snapshot):
        self.require_access()
        page, project = self.require_project(snapshot["project_id"], snapshot["revision"], permission=None, idle=False)
        current = self.snapshot(page, project)
        if any(current[key] != snapshot.get(key) for key in ("project_path", "project_fingerprint")):
            raise BridgeError("stale_project", "工程内容或路径已变化；保留任务结果，请重新核对。")
        return page, project

    def new_job(self, kind, snapshot):
        self.require_access()
        self.require_idle()
        job = {"job_id": uuid.uuid4().hex, "kind": kind, "status": "running", **snapshot,
               "created_at": time.time(), "updated_at": time.time(), "progress": {},
               "result": {}, "error": None, "message": ""}
        self.jobs[job["job_id"]] = job
        self._persist()
        return job

    def public_job(self, job):
        return {"protocol": PROTOCOL, **copy.deepcopy(job)}

    def update_job(self, job, **fields):
        job.update(fields, updated_at=time.time())
        self._persist()
        return self.public_job(job)

    def finish_job(self, job, result, status="completed"):
        # A cancelled request may finish native I/O; preserve its output evidence.
        if job.get("status") == "cancelling":
            status = "cancelled"
        self.cancel_callbacks.pop(job["job_id"], None)
        return self.update_job(job, status=status, result=result, error=None)

    def fail_job(self, job, exc):
        error = error_info(exc)
        status = "cancelled" if error["code"] == "cancelled" or job.get("status") == "cancelling" else "failed"
        self.cancel_callbacks.pop(job["job_id"], None)
        if status == "cancelled" and job.get("kind") in ("glossary_proofread", "sentence_refine"):
            job.setdefault("result", {}).setdefault("cancellation", {
                "request_state": "unknown", "result_received": False,
                "applied": False, "retry_safe": False})
        return self.update_job(job, status=status, error=error, message=error["message"])

    def get_owned_job(self, job_id, kind=None):
        job = self.jobs.get(str(job_id))
        if job is None or (kind and job.get("kind") != kind):
            raise BridgeError("unknown_job", "找不到此 MCP 制作任务。")
        return job

    def run_job(self, kind, snapshot, work, apply=None, *, check_before_apply=True,
                existing_job=None, summarize_cancelled=None):
        from ..recognition.service import CancellationToken
        if existing_job is None:
            job = self.new_job(kind, snapshot)
        else:
            job = existing_job
            if (self.jobs.get(job.get("job_id")) is not job or job.get("kind") != kind
                    or job.get("status") != "running"):
                raise BridgeError("invalid_job", "无法继续不属于本操作的任务。")
            self.require_access()
            self.require_idle(exclude_job_id=job["job_id"])
            self.update_job(job, **snapshot)
        job_id = job["job_id"]
        token = CancellationToken()
        worker = _JobThread(job_id, work, token, self)
        self._tokens[job_id] = token
        self._workers[job_id] = worker
        self._apply_callbacks[job_id] = (apply, check_before_apply)
        self._cancel_summaries[job_id] = summarize_cancelled
        self.cancel_callbacks[job_id] = token.cancel
        worker.result_ready.connect(self._job_done)
        worker.failed.connect(self._job_failed)
        worker.progress_changed.connect(self._job_progress)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return self.public_job(job)

    @Slot(str, object)
    def _job_done(self, job_id, result):
        job = self.jobs[job_id]
        callback, check = self._apply_callbacks.pop(job_id)
        summarize_cancelled = self._cancel_summaries.pop(job_id, None)
        try:
            if job.get("status") == "cancelling" or self._closed:
                self.job_payloads[job_id] = result
                summary = {}
                try:
                    if summarize_cancelled is not None:
                        summary = summarize_cancelled(result, job)
                    elif isinstance(result, dict):
                        summary = result
                    # Only persist the deliberately public JSON receipt, never a
                    # provider/native object repr that could contain credentials.
                    summary = json.loads(json.dumps(summary, ensure_ascii=False))
                    if not isinstance(summary, dict):
                        summary = {}
                except Exception as exc:
                    summary = {"summary_error": error_info(exc)}
                summary["cancellation"] = {"result_received": True, "applied": False, "retry_safe": False}
                self.finish_job(job, summary, status="cancelled")
                return
            if callback is not None:
                if check and job.get("project_id"):
                    self.check_snapshot(job)
                result = callback(result, job)
                if result is DEFERRED:
                    return
            self.finish_job(job, result)
        except Exception as exc:
            self.job_payloads.setdefault(job_id, result)
            self.fail_job(job, exc)
        finally:
            self._workers.pop(job_id, None)
            self._tokens.pop(job_id, None)

    @Slot(str, object)
    def _job_failed(self, job_id, exc):
        self._apply_callbacks.pop(job_id, None)
        self._cancel_summaries.pop(job_id, None)
        self._workers.pop(job_id, None)
        self._tokens.pop(job_id, None)
        self.fail_job(self.jobs[job_id], exc)

    @Slot(str, object)
    def _job_progress(self, job_id, value):
        job = self.jobs.get(job_id)
        if job and job.get("status") in ACTIVE:
            self.update_job(job, progress=value if isinstance(value, dict) else {"message": safe_message(value)})

    def op_get_job(self, job_id):
        self.require_access()
        return self.public_job(self.get_owned_job(job_id))

    def op_cancel_job(self, job_id):
        self.require_access()
        job = self.get_owned_job(job_id)
        if job.get("status") not in ACTIVE:
            return self.public_job(job)
        callback = self.cancel_callbacks.get(job_id)
        if callback is None:
            raise BridgeError("cancel_unavailable", "此任务没有可用的原生取消句柄；请查询原任务，不自动重发。")
        self.update_job(job, status="cancelling", message="已请求取消，等待原生任务确认。")
        callback()
        return self.public_job(job)

    def stop(self, reason=""):
        self._closed = True
        for pending in getattr(self, "recognition_handoffs", {}).values():
            pending["valid"] = False
        for job_id, callback in list(self.cancel_callbacks.items()):
            job = self.jobs[job_id]
            if job.get("status") in ACTIVE:
                self.update_job(job, status="cancelling", message="MCP 访问已关闭，正在取消任务。")
                callback()

    def permissions_changed(self, previous, current):
        """Revocation also stops work already in flight, without changing settings."""
        access_changed = (not current.get("enabled") or previous.get("scope") != current.get("scope"))
        edits_revoked = previous.get("allow_edits") and not current.get("allow_edits")
        if access_changed or edits_revoked:
            for pending in getattr(self, "recognition_handoffs", {}).values():
                pending["valid"] = False
        for job_id, callback in list(self.cancel_callbacks.items()):
            job = self.jobs[job_id]
            kind = job["kind"]
            export_revoked = (kind == "export_video" and (not current.get("allow_export")
                              or previous.get("export_dir") != current.get("export_dir")))
            text_revoked = (previous.get("allow_glossary") and not current.get("allow_glossary")
                            and kind in ("glossary_proofread", "stutter_cleanup", "recognition"))
            write_revoked = edits_revoked and kind != "detect_speech_pauses" and kind != "export_video"
            if job.get("status") in ACTIVE and (access_changed or export_revoked or text_revoked or write_revoked):
                self.update_job(job, status="cancelling", message="原生MCP权限或范围已变化，正在取消任务。")
                callback()

    def dispatch(self, method, **params):
        if method not in OPERATIONS:
            raise BridgeError("unknown_method", method)
        self.require_access()
        return getattr(self, "op_" + method)(**params)


def make_production_service(bridge):
    from .production_media import MediaOperations
    from .production_recognition import RecognitionOperations
    from .production_text import TextOperations

    class ProductionService(MediaOperations, RecognitionOperations, TextOperations, ProductionCore):
        pass

    return ProductionService(bridge)
