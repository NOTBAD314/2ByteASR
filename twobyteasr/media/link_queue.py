"""Serial, persistent download queue; coalesced polling, no Qt/window callbacks."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import threading
import time

from .link_download import DownloadEngine, redact
from .link_manifest import MANIFEST_NAME, atomic_json, load_bundle, reprocess_subtitles
from .link_reconstruction import MODES
from .link_tools import DownloadCancelled, check_cancel
from .media_ingest import ingest_media

TERMINAL = {"pending_import", "imported", "partial", "failed", "cancelled", "paused"}


class DownloadQueue:
    def __init__(self, storage: Path, engine=None):
        self.storage = Path(storage)
        self.engine = engine or DownloadEngine()
        self.tasks = {}
        self._secrets, self._events = {}, {}
        self._condition = threading.Condition(threading.RLock())
        self._cancel = threading.Event()
        self._closed = False
        self._active = ""
        self._active_authorization = None
        self._revision = 0
        if self.storage.is_file():
            try:
                saved = json.loads(self.storage.read_text(encoding="utf-8"))
                for task in saved.get("tasks", [])[-100:]:
                    # Restart never restores authority to a UI session or resumes network automatically.
                    task["auto_import"] = False
                    task["target"] = {}
                    if task["state"] not in TERMINAL:
                        task["state"] = "paused"
                    self.tasks[task["task_id"]] = task
            except (ValueError, OSError, KeyError, TypeError):
                pass
        self._thread = threading.Thread(target=self._run, daemon=True, name="link-download-queue")
        self._thread.start()

    def _save(self):
        atomic_json(self.storage, dict(version=1, tasks=list(self.tasks.values())[-100:]))
        self._revision += 1

    def add(self, task, *, proxy="", cookie_file=""):
        with self._condition:
            if self._closed:
                raise ValueError("下载队列已关闭。")
            if task["task_id"] in self.tasks:
                return
            if sum(t["state"] not in TERMINAL for t in self.tasks.values()) >= 100:
                raise ValueError("队列最多保留 100 个未完成任务。")
            snapshot = self.tasks[task["task_id"]] = copy.deepcopy(task)
            snapshot["public_download"] = not bool(cookie_file)
            if snapshot["public_download"]:
                for previous in reversed(tuple(self.tasks.values())):
                    if (previous["task_id"] != snapshot["task_id"] and previous.get("public_download")
                            and previous["state"] in {"imported", "pending_import", "partial"}
                            and all(previous.get(key) == snapshot.get(key) for key in
                                ("url", "platform", "video_id", "video_format", "audio_format"))
                            and set(snapshot.get("track_ids", [])).issubset(previous.get("track_ids", []))):
                        snapshot["reuse_from"] = previous["directory"]
                        break
            self._secrets[task["task_id"]] = dict(proxy=proxy, cookie_file=cookie_file)
            self._save()
            self._condition.notify()

    def snapshots(self):
        with self._condition:
            return copy.deepcopy(list(self.tasks.values()))

    def history_snapshot(self, revision):
        with self._condition:
            if revision == self._revision:
                return revision, None
            return self._revision, copy.deepcopy(list(self.tasks.values()))

    def events(self):
        with self._condition:
            values = list(self._events.values())
            self._events.clear()
            return values

    def cancel(self, task_id):
        with self._condition:
            task = self.tasks[task_id]
            task.pop("pause_requested", None)
            if self._active == task_id:
                task["state"] = "cancelling"
                self._cancel.set()
            elif task["state"] in ("queued", "paused"):
                task["state"] = "cancelled"
                self._secrets.pop(task_id, None)
            self._save()

    def pause(self, task_id):
        """Stop like cancel, but finish as paused; resume continues the partial files."""
        with self._condition:
            task = self.tasks[task_id]
            if self._active == task_id:
                task.update(state="pausing", pause_requested=True)
                self._cancel.set()
            elif task["state"] == "queued":
                task["state"] = "paused"
                self._secrets.pop(task_id, None)
            self._save()

    def revoke(self, authorization):
        with self._condition:
            authorization.revoke()
            if self._active_authorization is authorization:
                self.cancel(self._active)
            for task_id, secrets in tuple(self._secrets.items()):
                if secrets.get("cookie_file") is authorization:
                    self.cancel(task_id)

    def resume(self, task_id, *, proxy="", cookie_file=""):
        """Paused work keeps its import target; the import still checks it is current."""
        with self._condition:
            task = self.tasks[task_id]
            if self._active == task_id or task["state"] != "paused":
                raise ValueError("只有已暂停的任务可以继续。")
            task.update(state="queued", error="")
            if cookie_file:
                task["public_download"] = False
                task.pop("reuse_from", None)
            task.pop("pause_requested", None)
            self._secrets[task_id] = dict(proxy=proxy, cookie_file=cookie_file)
            self._save()
            self._condition.notify()

    def clear_finished(self):
        """Forget imported and cancelled rows; their files stay on disk."""
        with self._condition:
            for key in [k for k, t in self.tasks.items() if t["state"] in {"imported", "cancelled"}]:
                del self.tasks[key]
            self._save()

    def retry(self, task_id, *, subtitles_only=False, proxy="", cookie_file=""):
        with self._condition:
            task = self.tasks[task_id]
            if self._active == task_id or task["state"] not in TERMINAL:
                raise ValueError("任务仍在运行。")
            task.update(state="queued", subtitles_only=bool(subtitles_only), error="", auto_import=False)
            task.pop("reprocess_mode", None)
            if cookie_file:
                task["public_download"] = False
                task.pop("reuse_from", None)
            self._secrets[task_id] = dict(proxy=proxy, cookie_file=cookie_file)
            self._save()
            self._condition.notify()

    def reprocess(self, task_id, mode):
        with self._condition:
            task = self.tasks[task_id]
            if self._active == task_id or task["state"] not in TERMINAL:
                raise ValueError("任务仍在运行。")
            if not task.get("downloaded_subtitles") or mode not in MODES:
                raise ValueError("没有可重新处理的字幕原稿。")
            task.update(state="queued", reprocess_mode=mode, error="", auto_import=False)
            self._save()
            self._condition.notify()

    def imported(self, task_id, result):
        with self._condition:
            task = self.tasks[task_id]
            task.update(state="imported", import_result=copy.deepcopy(result))
            self._save()

    def pending(self, task_id, message=""):
        with self._condition:
            task = self.tasks[task_id]
            task.update(state="pending_import", auto_import=False, import_note=message)
            self._save()

    def _publish(self, task_id, data):
        with self._condition:
            self._events[task_id] = dict(data, task_id=task_id)

    def _prepare_bundle(self, manifest_path):
        bundle = load_bundle(Path(manifest_path), verify_media=True)
        if bundle["media_path"]:
            bundle["media_result"] = ingest_media(bundle["media_path"], generation=0, project_token="", discover_subtitles=False)
            if bundle["media_result"].error:
                raise ValueError(bundle["media_result"].error)
        return bundle

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or any(t["state"] == "queued" for t in self.tasks.values()))
                if self._closed:
                    return
                task = next(t for t in self.tasks.values() if t["state"] == "queued")
                key = task["task_id"]
                self._active = key
                self._cancel.clear()
                task["state"] = "running"
                snapshot = copy.deepcopy(task)
                secrets = self._secrets.pop(key, {})
                self._active_authorization = secrets.get("cookie_file")
                self._save()
            bundle = None
            reprocessed = False
            try:
                def report(data):
                    self._publish(key, data)
                if snapshot.get("reprocess_mode"):
                    path = reprocess_subtitles(Path(snapshot["directory"]) / MANIFEST_NAME, key,
                        snapshot["reprocess_mode"], cancel=self._cancel.is_set, notify=report)
                    reprocessed = True
                else:
                    path = self.engine.download(snapshot, cancel=self._cancel.is_set,
                        notify=report, **secrets, subtitles_only=snapshot.get("subtitles_only", False))
                check_cancel(self._cancel.is_set)
                bundle = self._prepare_bundle(path)
                check_cancel(self._cancel.is_set)
                state = "partial" if bundle["manifest"].get("errors") else "pending_import"
                error = " ".join(item.get("message", "") for item in bundle["manifest"].get("errors", []))
            except DownloadCancelled as exc:
                with self._condition:
                    paused = task.pop("pause_requested", False)
                state, error = ("paused", "") if paused else ("cancelled", str(exc))
            except Exception as exc:
                state, error = "failed", redact(exc)
                path = Path(snapshot["directory"])/MANIFEST_NAME
                if path.is_file():
                    try:
                        candidate = self._prepare_bundle(path)
                        if candidate["manifest"].get("media") or candidate["manifest"].get("subtitles"):
                            bundle, state = candidate, "partial"
                    except Exception:
                        pass
            with self._condition:
                task.update(state=state, error=error)
                self._active = ""
                self._active_authorization = None
                if bundle and state in {"pending_import", "partial"}:
                    subtitles = bundle["manifest"].get("subtitles", ())
                    task["downloaded_subtitles"] = len(subtitles)
                    ai = next((sub["ai"] for sub in subtitles if sub.get("ai")), None)
                    if ai is not None:
                        task["subtitle_ai"] = {k: ai[k] for k in ("status", "applied", "fallback")}
                    elif reprocessed:
                        task.pop("subtitle_ai", None)
                    if reprocessed:
                        task["subtitle_mode"] = snapshot["reprocess_mode"]
                        task.pop("reprocess_mode", None)
                self._events[key] = dict(task_id=key, state=state, error=error, bundle=bundle, terminal=True)
                self._save()

    def close(self):
        with self._condition:
            self._closed = True
            self._cancel.set()
            self._secrets.clear()
            for task in self.tasks.values():
                if task["state"] == "queued":
                    task["state"] = "paused"
            self._condition.notify_all()
            self._save()
        # Downloader is cancelled even if its stdout is silent.
        self._thread.join(timeout=3)
