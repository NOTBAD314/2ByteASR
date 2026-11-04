"""Durable recognition ownership and checkpoints, independent of pages/reports.

One OS lease owns execution. A per-task JSON journal is the source of truth;
history indexes are disposable. Artifacts are published before their receipt.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from ..storage.atomic_files import write_text_atomic

ACTIVE = {"queued", "running"}
TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted", "no_speech", "needs_recovery", "empty_result"}
_SECRET = re.compile(r"(?i)(?:api_?key|access_?token|authorization|password|secret|credential)")


class TaskBusy(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def task_root():
    from ..runtime_paths import user_data_root
    return user_data_root() / "recognition-tasks"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def file_digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def public_config(value):
    """Persist credential references, never resolved credentials or auth URLs."""
    from urllib.parse import urlsplit, urlunsplit
    if isinstance(value, dict):
        return {str(k): public_config(v) for k, v in value.items()
                if not (_SECRET.search(str(k)) and not str(k).endswith(("_env", "_source", "_configured")))
                and str(k).lower() not in {"token", "headers", "cookies"}}
    if isinstance(value, (list, tuple)):
        return [public_config(v) for v in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    return value


def options_payload(options):
    result = asdict(options)
    for key in tuple(result):
        if key.endswith("_json") and result[key]:
            result[key] = json.dumps(public_config(json.loads(result[key])), ensure_ascii=False)
    return public_config(result)


def _process_identity():
    try:
        import psutil
        return {"pid": os.getpid(), "created": psutil.Process().create_time()}
    except (ImportError, OSError):
        return {"pid": os.getpid(), "created": None}


def _alive(owner):
    try:
        import psutil
        process = psutil.Process(int(owner.get("pid") or 0))
        return process.is_running() and (owner.get("created") is None or
                                         abs(process.create_time() - owner["created"]) < .01)
    except Exception:
        return False


class FileLease:
    """Kernel releases this lock on exit/crash; elapsed time never steals it."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if handle.seek(0, 2) == 0:
                    handle.write(b"0"); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            raise TaskBusy("任务已有执行者，不能重复接管。") from None
        self.handle = handle
        return self

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.close()


def read_record(path):
    path = Path(path)
    for candidate in (path, path.with_name("task.previous.json")):
        try:
            row = json.loads(candidate.read_text(encoding="utf-8"))
            if row.get("journal_version") == 1 and row.get("job_id") == path.parent.name:
                return row
        except (OSError, ValueError, AttributeError):
            continue
    raise ValueError(f"任务记录不可读取：{path.parent.name}；其余任务仍可使用。")


class TaskJournal:
    def __init__(self, job_id, root=None):
        from .recognition_result import validate_job_id
        self.job_id = validate_job_id(job_id)
        self.directory = Path(root or task_root()) / self.job_id
        self.path = self.directory / "task.json"
        self.lock = threading.RLock()
        self.record = None
        self._last_progress_write = 0.
        self._lease = None

    def create(self, media_paths, options):
        self.directory.mkdir(parents=True, exist_ok=True)
        with FileLease(self.directory / "create.lock"):
            if self.path.exists():
                self.record = read_record(self.path)
                return self
            inputs = []
            for value in media_paths:
                path = Path(value).absolute()
                item = {"path": str(path), "name": path.name}
                try:
                    stat = path.stat()
                    item.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                except OSError as exc:
                    item["input_error"] = str(exc)
                inputs.append(item)
            snapshot = options_payload(options)
            settings = json.loads(snapshot.get("settings_snapshot_json") or "{}")
            configuration=self._write_configuration(snapshot)
            self.record = dict(journal_version=1, job_id=self.job_id, status="queued", started_at=now(),
                media=inputs[0] if inputs else {}, settings=settings, stages=[], result={}, review_items=[],
                task={"inputs": inputs, "configuration": configuration, "attempts": [], "artifacts": {}, "cache_files": {},
                      "remote_requests": {}, "owner": _process_identity(), "last_progress_at": now(),
                      "current_stage": "等待启动", "created_epoch": time.time(), "elapsed_seconds": 0.})
            self._save(backup=False)
        return self

    def _write_configuration(self,snapshot):
        signature=digest(snapshot)
        name='configuration-'+signature+'.json'
        path=self.directory/name
        if not path.is_file():
            write_text_atomic(path,json.dumps(snapshot,ensure_ascii=False,separators=(',',':')))
        return {'file':name,'sha256':signature}

    def configure_run(self,options):
        with self.lock:
            reference=self._write_configuration(options_payload(options))
            self.record['task']['configuration']=reference
            self.record['task'].pop('options',None)
            if self.record['task']['attempts']:self.record['task']['attempts'][-1]['configuration']=reference
            self._save()

    def _save(self, *, backup=True):
        if backup and self.path.is_file():
            # A failed replacement leaves either this last complete record or the old one.
            previous=read_record(self.path)
            write_text_atomic(self.path.with_name("task.previous.json"), json.dumps(previous,ensure_ascii=False,separators=(',',':')))
        write_text_atomic(self.path, json.dumps(self.record, ensure_ascii=False, separators=(",", ":")))

    def acquire(self, *, resume=False):
        lease = FileLease(self.directory / "executor.lock").acquire()
        try:
            self.record = read_record(self.path)
            if self.record["status"] != "queued" and not resume:
                raise TaskBusy("已有任务只能从明确的继续处理入口恢复。")
            self.record["status"] = "running"
            task = self.record["task"]
            task["owner"] = _process_identity()
            task["attempts"].append({"id": uuid.uuid4().hex, "started_at": now(), "owner": task["owner"],
                                     "resume": bool(resume), "status": "running"})
            task["attempt_started_epoch"] = time.time()
            task['last_error']=''
            self.record.pop('finished_at',None)
            self._save()
            self._lease = lease
        except BaseException:
            lease.close()
            raise
        return self

    def close(self):
        if self._lease:
            self._lease.close(); self._lease = None

    def event(self, kind, payload):
        """Critical changes sync immediately. Ordinary progress is coalesced."""
        critical = kind in {"queue_configured", "media_started", "media_completed", "media_failed", "media_cancelled",
                            "stage_started", "stage_completed", "stage_failed", "stage_cancelled", "cache_write",
                            "CACHE_ACCEPTED", "asr_language_request", "asr_shard_ready", "studio_project_saved",
                            "studio_project_failed", "queue_failed", "queue_cancelled", "subtitle_delivery",
                            "task_cache_prepared", "ready_shard_completed", "ready_shard_failed", "ready_shard_queued"}
        critical = critical or kind in {'remote_submission_intent', 'remote_task_accepted', 'mosi_scheduler', 'pipeline_work_progress'}
        if not critical and time.monotonic() - self._last_progress_write < 2.:
            return
        with self.lock:
            task = self.record["task"]
            if kind == "queue_configured":
                self.record["settings"] = public_config(payload.get("runtime_settings") or {})
            if kind == 'task_cache_prepared':
                task.setdefault('cache_directories', {})[str(payload['cache_dir'])] = payload['identity']
            if kind == "media_started":
                task["media_index"] = int(payload.get("media_index") or 1)
                task["current_input"] = str(payload.get("media_path") or "")
            if kind.startswith("stage_"):
                index = payload.get("index")
                key = (task.get("media_index", 1), index, payload.get('shard_id', ''))
                stage = next((r for r in self.record["stages"] if (r.get("media_index", 1),r.get("index"),r.get('shard_id','')) == key), None)
                if stage is None:
                    stage = {"index": index, "media_index": key[0], 'shard_id':key[2]}
                    self.record["stages"].append(stage)
                stage.update({k: public_config(v) for k,v in payload.items()
                              if k in {"label", "resource", "elapsed_seconds", "error"}})
                stage["status"] = {"stage_started":"running", "stage_completed":"completed",
                                   "stage_failed":"failed", "stage_cancelled":"cancelled"}.get(kind, "skipped")
                task["current_stage"] = str(stage.get("label") or "")
            if kind=='pipeline_work_progress':
                work_id=str(payload.get('work_id') or '')
                works=task.setdefault('work_items',{})
                works[work_id]={k:payload[k] for k in ('label','state','done','total','phase','elapsed_seconds','shard_id') if k in payload}
                active=[str(r.get('label') or '') for r in works.values() if r.get('state') in {'running','queued','retry'}]
                task['current_stage']='；'.join(active[:4]) if active else str(payload.get('label') or '')
            if kind in {"cache_write", "CACHE_ACCEPTED"} and payload.get("path"):
                path = Path(payload["path"])
                if path.is_file():
                    task["cache_files"][str(path)] = {"stage": payload.get("stage"), "bytes": path.stat().st_size,
                                                     "sha256": file_digest(path)}
            if kind in {"asr_language_request", "asr_shard_ready"}:
                key = str(payload.get("request_index", payload.get("index", 0)))
                task["remote_requests"].setdefault(key, {}).update({k:v for k,v in payload.items()
                    if k in {"remote_task_id", "raw_result_path", "start", "end", "request_index", "state"}})
            if kind in {'remote_submission_intent','remote_task_accepted'}:
                task.setdefault('submissions',{})[str(payload['request_key'])]=dict(payload)
            if kind == 'mosi_scheduler':
                task['remote_total']=int(payload.get('request_total') or 0)
            if kind in {'ready_shard_completed','ready_shard_failed','ready_shard_queued'}:
                task.setdefault('shards',{})[str(payload.get('shard_id'))]={
                    'status':'completed' if kind.endswith('completed') else 'failed' if kind.endswith('failed') else 'queued',
                    'version':str(payload.get('input_version') or ''),
                    'cue_count':int(payload.get('cues') or 0),'error':str(payload.get('error') or '')}
            if kind == "studio_project_saved":
                self.record["result"].update(cue_count=int(payload.get("cue_count") or 0),
                    outputs={"project": str(payload.get("project_path") or "")})
            if kind.endswith(("failed", "cancelled")):
                task["last_error"] = str(payload.get("error") or "")[:2000]
            progressed=critical or kind=='cloud_batch_completed'
            if kind in {'asr_progress','asr_worker_progress'}:
                measured={key:payload[key] for key in ('completed','completed_chunks','processed_end','processed_seconds','worker_state') if key in payload}
                prior=task.setdefault('progress_values',{}).get(kind)
                progressed=bool(measured) and measured!=prior
                task['progress_values'][kind]=measured
            if progressed:
                task["last_progress_at"] = now()
            task["last_event"] = kind
            task["heartbeat_at"] = now()
            self.record["result"]["elapsed_seconds"] = task.get("elapsed_seconds", 0.) + max(0., time.time()-task.get("attempt_started_epoch", time.time()))
            self._save(backup=critical)
            self._last_progress_write = time.monotonic()

    def publish(self, key, payload, dependency):
        """Self-validating envelope is recoverable even before the journal commit."""
        dep = digest(dependency)
        name = hashlib.sha256((key + dep).encode()).hexdigest() + ".json"
        path = self.directory / "artifacts" / name
        envelope = {"version": 1, "key": key, "dependency": dep, "sha256": digest(payload), "payload": payload}
        write_text_atomic(path, json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
        with self.lock:
            self.record["task"]["artifacts"][key] = {"path": str(path), "dependency": dep, "sha256": envelope["sha256"]}
            self._save()
        return path

    def load_artifact(self, key, dependency):
        dep = digest(dependency)
        path = self.directory / "artifacts" / (hashlib.sha256((key+dep).encode()).hexdigest()+".json")
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("key") != key or row.get("dependency") != dep or digest(row["payload"]) != row["sha256"]:
                return None
            return row["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def finish(self, results=(), *, status=None, error=""):
        with self.lock:
            if status is None:
                statuses = [row.status for row in results]
                status = ("cancelled" if "cancelled" in statuses else "failed" if statuses and all(s=="failed" for s in statuses)
                          else "partial" if any(s not in {"success", "no_speech", "skipped"} for s in statuses) else "completed")
                if len(statuses)==1 and statuses[0] in {'no_speech','needs_recovery','empty_result'}:status=statuses[0]
                if not statuses:status='failed';error=error or '没有可以处理的素材。'
                if statuses and all(s in {'success','degraded_success','no_speech','skipped'} for s in statuses):
                    outcomes=[]
                    for item in results:
                        try:
                            from .recognition_outcome import normalize_recognition_outcome
                            report=json.loads(Path(item.report_json_path).read_text(encoding='utf-8'))
                            translated_incomplete=any(r.get('category') in {'翻译未全部完成','翻译未完成'} for r in report.get('review_items',[]))
                            outcomes.append('partial' if translated_incomplete else normalize_recognition_outcome(report).core_status)
                        except (OSError,ValueError,TypeError):outcomes.append('partial' if item.status=='degraded_success' else 'completed')
                    if all(value in {'completed','no_speech','skipped'} for value in outcomes):
                        status='no_speech' if outcomes==['no_speech'] else 'completed'
            self.record["status"] = status
            self.record["finished_at"] = now()
            task = self.record["task"]
            if task.get('attempts') and task['attempts'][-1].get('status')=='running':
                self.record['result']['elapsed_seconds']=task.get('elapsed_seconds',0.)+max(0.,time.time()-task.get('attempt_started_epoch',time.time()))
            task["elapsed_seconds"] = self.record["result"].get("elapsed_seconds",0.)
            if status in {'interrupted','failed','cancelled'}:
                for stage in self.record['stages']:
                    if stage.get('status')=='running':stage['status']=status
                for work in task.get('work_items',{}).values():
                    if work.get('state') in {'running','queued','retry'}:work['state']=status
            task["last_error"] = error or task.get("last_error", "")
            if results:
                task["results"] = [asdict(r) for r in results]
                task["reports"] = [r.report_json_path for r in results if r.report_json_path]
                for r in results:
                    if r.project_path:
                        self.record["result"].setdefault("outputs", {})["project"] = r.project_path
            if task["attempts"]:
                task["attempts"][-1].update(status=status, finished_at=now(), error=error)
            self._save()


def reconcile(path):
    """Mark an orphan only after acquiring its OS execution lock."""
    path = Path(path)
    row = read_record(path)
    if row["status"] not in ACTIVE:
        return row
    if row["status"] == "queued" and _alive(row["task"].get("owner", {})):
        return row
    journal = TaskJournal(row["job_id"], path.parent.parent)
    try:
        with FileLease(path.parent / "executor.lock"):
            journal.record = read_record(path)
            if journal.record["status"] in ACTIVE:
                journal.finish(status="interrupted", error="执行者已退出；已保存的阶段结果保留，可继续处理。")
            return journal.record
    except TaskBusy:
        return row


def history_paths(root=None):
    base=Path(root or task_root())
    paths=set(base.glob('*/task.json'))|{p.with_name('task.json') for p in base.glob('*/task.previous.json')}
    for path in sorted(paths):
        try:
            if not path.is_file():
                with FileLease(path.parent/'executor.lock'):
                    journal=TaskJournal(path.parent.name,base);journal.record=read_record(path);journal._save(backup=False)
            reconcile(path)
        except (OSError, ValueError, TaskBusy):
            pass  # A corrupt task must not hide the rest of the list.
        yield path


def protected_paths(root=None):
    result = set()
    for path in Path(root or task_root()).glob("*/task.json"):
        try:
            row = read_record(path)
            if row["status"] != "completed":
                result.update(row['task'].get('cache_directories', {}))
                result.update(row["task"].get("cache_files", {}))
                for request in row["task"].get("remote_requests", {}).values():
                    if request.get("raw_result_path"):
                        result.add(str(Path(request["raw_result_path"]).parent.parent))
                for request in row['task'].get('submissions',{}).values():
                    if request.get('state_path'):result.add(str(Path(request['state_path']).parent.parent))
        except (OSError, ValueError):
            continue
    return result


def depends_on(path, references):
    candidate = os.path.normcase(os.path.abspath(path))
    return any(candidate == os.path.normcase(os.path.abspath(ref)) or
               candidate.startswith(os.path.normcase(os.path.abspath(ref)).rstrip('\\/') + os.sep)
               for ref in references)


def report_payload(path):
    row = read_record(path)
    if row['status']=='running':
        task=row['task']
        row['result']['elapsed_seconds']=task.get('elapsed_seconds',0.)+max(0.,time.time()-task.get('attempt_started_epoch',time.time()))
    reports = ([row['task']['optional_report']] if row['task'].get('optional_report') else [])+row['task'].get('reports', [])
    if reports:
        try:
            final = json.loads(Path(reports[0]).read_text(encoding='utf-8'))
            if final.get('job_id') == row['job_id']:
                for key in ('result', 'review_items', 'polishing_summary', 'terminology_status', 'events'):
                    if key in final:
                        row[key] = final[key]
        except (OSError, ValueError, TypeError):
            pass
    return row


def record_optional_result(project,report,unit,path):
    """A saved stage retry updates the same task, retaining historical reports."""
    job=str((project.generation_metadata or {}).get('job_id') or report.get('job_id') or '')
    if not job:return
    journal=TaskJournal(job)
    if not journal.path.is_file():return
    try:
        with FileLease(journal.directory/'executor.lock'):
            journal.record=read_record(journal.path)
            expected=journal.record.get('result',{}).get('outputs',{}).get('project')
            if not expected or os.path.normcase(str(Path(expected).resolve()))!=os.path.normcase(str(Path(path).resolve())):return
            from .processing_recovery import effective_report,failure_summary
            summary=failure_summary(project,report)
            current=effective_report(project,report,summary=summary)
            current['job_id']=job
            target=journal.directory/'optional-report.json'
            write_text_atomic(target,json.dumps(current,ensure_ascii=False,separators=(',',':')))
            task=journal.record['task']
            task['optional_report']=str(target)
            task.setdefault('optional_attempts',[]).append({'stage':unit.get('stage'),
                'unit_key':unit.get('key'),'status':unit.get('status'),'recorded_at':now()})
            if journal.record['status'] in {'partial','completed'}:
                journal.record['status']='partial' if summary['failed_tasks'] or summary['pending_proposals'] else 'completed'
            task['last_progress_at']=now();journal.record['finished_at']=now()
            journal._save()
    except (TaskBusy,OSError):
        return  # A live primary executor owns its journal; no stale takeover.


def resume_options(path, current_settings):
    from .service import RunOptions
    row = reconcile(path)
    if row['status'] in ACTIVE:
        raise TaskBusy('任务仍有执行者。')
    reference=row['task'].get('configuration')
    if reference:
        name=str(reference['file'])
        if Path(name).name!=name:raise ValueError('任务配置路径无效。')
        payload=json.loads((Path(path).parent/name).read_text(encoding='utf-8'))
        if digest(payload)!=reference['sha256']:raise ValueError('任务配置校验失败，未使用当前设置替代原任务。')
    else:
        payload = dict(row['task']['options'])
    # Reload credentials from the current process; preserve the task's public
    # model/endpoint/configuration. Account-scoped ASR caches still validate.
    def overlay(base, saved):
        result = dict(base)
        for key, value in saved.items():
            result[key] = overlay(result.get(key, {}), value) if isinstance(value, dict) else value
        return result
    saved = json.loads(payload.get('settings_snapshot_json') or '{}')
    payload['settings_snapshot_json'] = json.dumps(overlay(current_settings, saved), ensure_ascii=False)
    payload.update(job_id=row['job_id'], resume=True, retry_incomplete=row['status']=='partial',
                   force_refresh_polish=False, force_refresh_group=False)
    return RunOptions(**payload), [r['path'] for r in row['task']['inputs']]
