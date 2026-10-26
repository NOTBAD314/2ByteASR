"""Versioned local diagnostic events. No Qt, model imports or network access.

The producer only sanitizes bounded metadata and enqueues it. One writer owns
rotation, human-readable rendering and snapshot barriers. Payloads never carry
subtitle bodies; explicit content attachments live in the report UI instead.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import itertools
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit
import uuid

FORMAT_VERSION = 1
MAX_EVENT_BYTES = 16 * 1024
FILE_BYTES = 2 * 1024 * 1024
SEGMENTS = 6
RETENTION_DAYS = 14
TOTAL_BYTES = 200 * 1024 * 1024
_CONTEXT = ContextVar("diagnostic_context", default={})
_FALLBACK_SALT = secrets.token_bytes(32)
_TOKEN = re.compile(r"(?i)(?:\b(?:sk|sk-proj|sk-ant|xai|ghp|gho|github_pat|glpat|gsk)[-_][A-Za-z0-9_-]{5,}|\b(?:AIza|LTAI|ya29\.)[A-Za-z0-9_.-]{10,}|\beyJ[A-Za-z0-9_.-]{16,})")
_SECRET = re.compile(r'''(?ix)(["']?(?:authorization|proxy-authorization|cookie|set-cookie|api[_-]?key|access[_-]?key(?:id|secret)?|(?:access|refresh|id)?[_-]?token|password|passwd|secret|signature|x-amz-signature)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''')
_PRIVATE_KEY = re.compile(r"(?i)(?:^|_)(?:text|preedit|commit_string|secret|token|password|api_key|access_key|subscription_key|private_key|client_secret|body|messages|content|prompt|response_body|raw_response|payload|cookie|authorization|description)(?:_|$)")
_SECRET_ALIASES = {"apikey","xapikey","accesstoken","refreshtoken","idtoken","authtoken",
                   "sessiontoken","proxyauthorization","proxycredentials","proxypassword",
                   "clientsecret","privatekey","secretkey","accesskey","accesskeyid","accesskeysecret",
                   "subscriptionkey","ocpapimsubscriptionkey","setcookie"}
_PRIVATE_HEADER_LINE = re.compile(r'''(?im)((?:proxy[-_]?authorization|authorization|set[-_]?cookie|cookie)["']?\s*[:=]\s*)[^\r\n]*''')
_PUBLIC_HEADERS = {"contenttype","contentlength","requestid","xrequestid","xmsrequestid",
                   "xamznrequestid","xcorrelationid","traceparent","date","retryafter"}
_PATH = re.compile(r'''(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n"<>|]*|(?<![\w:])/(?:home|Users|tmp|var|mnt|media|opt)/[^\r\n"<>|]*''')
_LABELS = {
    "window.motion": "窗口移动与位置修正",
    "session.start": "診斷會話開始", "session.end": "診斷會話結束",
    "operation.start": "開始操作", "operation.end": "操作結束",
    "command.received": "收到應用程式命令", "command.result": "命令處理結果",
    "data.begin": "開始修改工程資料", "data.commit": "工程資料已提交",
    "data.rollback": "資料驗證失敗，已回復", "view.applied": "畫面已套用資料變化",
    "view.failed": "資料已提交，但畫面更新失敗", "view.snapshot": "畫面狀態快照",
    "problem.marked": "使用者標記事發時間", "background.start": "背景任務開始",
    "background.result": "背景結果歸屬判定", "project.open": "開啟工程",
    "project.save": "儲存工程", "project.loaded": "工程資料載入完成",
    "player.command": "播放器命令", "player.state": "播放器狀態改變",
    "ai.validation": "AI 資料檢查與後續處置", "process.start": "子程序啟動",
    "process.end": "子程序結束", "process.failure": "子程序失敗",
    "python.exception": "Python 例外", "thread.exception": "背景執行緒例外",
    "async.exception": "非同步任務例外", "qt.message": "Qt 診斷訊息",
    "diagnostics.loss": "診斷記錄有截斷或遺失", "diagnostics.mode": "詳細診斷模式改變",
    "export.start": "開始匯出診斷包", "export.end": "診斷包匯出結束",
    "timing.validation": "時間範圍檢查", "translation.links": "原文與譯文關聯變化",
    "project.saved": "工程已完成原子寫入", "player.intent": "收到播放／暫停意圖",
    "report.dialog": "問題回報窗口狀態", "diagnostics.observer": "部分診斷上下文無法取得",
}
_ACTIONS={"cue.select":"選取字幕","cue.add":"新增字幕","cue.edit":"修改字幕","cue.merge_pair":"合併字幕",
          "cue.split":"拆分字幕","cue.delete":"刪除字幕","cue.ripple_qw":"Q／W 邊界操作","cue.drag_commit":"拖動／修剪字幕",
          "project.load":"讀取工程","project.save":"儲存工程","project.save_revision":"寫入工程快照",
          "view.refresh":"刷新工作台","subtitle.export":"匯出字幕","subtitle.export_readback":"回讀檢查字幕",
          "player.play_pause":"播放／暫停","player.seek":"定位播放位置"}
_RESULTS={"started":"開始","completed":"完成","failed":"失敗","cancelled":"取消","skipped":"跳過",
          "not_run":"未執行","waiting":"等待","unknown":"未知","observed":"已記錄","accepted":"接納",
          "partial":"部分完成","received":"已收到"}
_SAMPLED = {"INPUT_RECEIVED", "INPUT_PAINT", "INPUT_METHOD_QUERY", "STUDIO_STATE", "GC_PAUSE",
            "PLAYHEAD", "PLAYBACK_TICK", "POSITION_CHANGED", "TIMELINE_PAINT"}
_BOUNDARIES={'operation.start','operation.end','data.begin','data.commit','data.rollback','view.failed',
             'project.loaded','project.saved','problem.marked','background.start','background.result','session.start','session.end'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Sanitizer:
    def __init__(self, salt=None):
        self.salt = salt or _FALLBACK_SALT
        self._key_cache = {}

    def key(self, value):
        value=str(value)
        cached=self._key_cache.get(value)
        if cached is not None:return cached
        cleaned=self.string(value)[:100]
        if len(self._key_cache)>=256:self._key_cache.clear()
        self._key_cache[value]=cleaned
        return cleaned

    def alias(self, value, kind="path"):
        if not value:
            return None
        value = str(value)
        if re.fullmatch(r"(?:project|path|source|fingerprint)-[a-f0-9]{16}(?:\.[a-z0-9]{1,10})?", value):
            return value
        digest = hmac.new(self.salt, value.replace("\\", "/").encode("utf8", "replace"), hashlib.sha256).hexdigest()[:16]
        ext = ""
        if kind in {"path", "source"}:
            match = re.search(r"(\.[a-zA-Z0-9]{1,10})$", value)
            if match:
                ext = match[1].lower()
        return kind + "-" + digest + ext

    def string(self, value):
        value = str(value)[:12000]
        for _ in range(3):
            value = value.replace('\\"', '"').replace("\\'", "'")
        # KEY-{5}: same pattern, written so a scan for committed private keys does not flag it.
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-{5}.*?(?:-----END [^-]*PRIVATE KEY-{5}|$)", "<credential>", value, flags=re.S)
        value = _PRIVATE_HEADER_LINE.sub(r"\1<credential>", value)
        value = re.sub(r"(?i)\bBearer\s+[^\s,'\";]+", "Bearer <credential>", value)
        value = _TOKEN.sub("<credential>", value)
        value = _SECRET.sub(r"\1<credential>", value)
        def url(match):
            try:
                return (urlsplit(match[0]).scheme + "://" + (urlsplit(match[0]).hostname or "unknown") + "/<redacted>")
            except ValueError:
                return "<url>"
        value = re.sub(r"(?i)https?://[^\s<>\"']+", url, value)
        value = _PATH.sub(lambda m: self.alias(m[0].strip(), "path"), value)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "<email>", value)
        return value[:2000]

    def clean(self, value, key="", depth=0):
        if depth > 8:
            return "<depth-limit>"
        key = str(key).casefold().replace("-", "_").replace(".", "_").replace(" ", "_")
        if isinstance(value,(int,float,bool)) and key.endswith(("_count","_characters","_bytes","_included","_tokens")):
            return value if not isinstance(value,float) or math.isfinite(value) else None
        if "headers" in key:
            def header_value(name, item):
                flat=re.sub(r"[^a-z0-9]","",str(name).casefold())
                return self.clean(item,"",depth+1) if flat in _PUBLIC_HEADERS else "<omitted>"
            if isinstance(value,dict):
                result={self.key(k):header_value(k,v) for k,v in itertools.islice(value.items(),80)}
                if len(value)>80:result["_omitted_headers"]=len(value)-80
                return result
            if isinstance(value,(list,tuple)):
                result=[]
                for item in value[:64]:
                    if isinstance(item,dict):
                        name=item.get("key") or item.get("name")
                        result.append({"name":self.string(name),"value":header_value(name,item.get("value"))})
                    elif isinstance(item,(list,tuple)) and len(item)==2:
                        result.append({"name":self.string(item[0]),"value":header_value(item[0],item[1])})
                    else:result.append("<omitted>")
                if len(value)>64:result.append({"_omitted_items":len(value)-64})
                return result
            return None if value is None else "<omitted>"
        if _PRIVATE_KEY.search(key) or key.replace("_","") in _SECRET_ALIASES or key in {"message", "error", "error_message", "stderr", "stdout", "command", "original_command", "args", "request", "response", "reason_text", "speaker_name", "project_name", "label", "window_title", "title"}:
            return "<omitted>"
        if key in {"project_id", "origin_project_id", "current_project_id", "source_project_id"}:
            return self.alias(value, "project")
        if key in {"snapshot_hash", "text_hash", "source_text_hash", "cue_digest", "caption_hash"}:
            return self.alias(value, "fingerprint")
        if isinstance(value, (Path, os.PathLike)) or (isinstance(value, str) and (key.endswith("path") or key in {"file", "filename"})):
            return self.alias(value, "path")
        if isinstance(value, dict):
            # Some transports expose headers/parameters as {name|key, value}
            # records instead of a mapping keyed by the actual header name.
            value_key=value.get("key") or value.get("name")
            if "value" in value:
                for candidate in (value.get("key"),value.get("name")):
                    if not isinstance(candidate,str):continue
                    normalized=candidate.casefold().replace("-","_").replace(".","_").replace(" ","_")
                    if _PRIVATE_KEY.search(normalized) or normalized.replace("_","") in _SECRET_ALIASES:
                        value_key=candidate
                        break
            result = {self.key(k): self.clean(v, value_key if k=="value" and isinstance(value_key,str) else str(k), depth+1)
                      for k, v in itertools.islice(value.items(), 80)}
            if len(value) > 80:
                result["_omitted_fields"] = len(value)-80
            return result
        if isinstance(value, (list, tuple, deque, set, frozenset)):
            result = [self.clean(v, "", depth+1) for v in itertools.islice(iter(value), 64)]
            if len(value) > 64:
                result.append({"_omitted_items": len(value)-64})
            return result
        if isinstance(value, str):
            return self.string(value)
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        return type(value).__name__


def exception_info(exc):
    """No locals/source lines/arbitrary exception bodies (may contain subtitles)."""
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen and len(chain) < 6:
        seen.add(id(exc))
        frames = []
        for f in traceback.extract_tb(exc.__traceback__)[-24:]:
            normalized = f.filename.replace("\\", "/")
            location = "twobyteasr/" + normalized.split("/twobyteasr/", 1)[1] if "/twobyteasr/" in normalized else Path(normalized).name
            frames.append(dict(module=location, line=f.lineno, function=f.name))
        chain.append(dict(type=type(exc).__name__, errno=getattr(exc, "errno", None),
                          frames=frames, detail="例外正文預設排除；依錯誤代碼與檢查欄位定位"))
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return {"chain": chain}


def current_context():
    return dict(_CONTEXT.get())


@contextmanager
def context(**fields):
    token = _CONTEXT.set({**_CONTEXT.get(), **fields})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def recorder():
    from . import editor_diagnostics
    return editor_diagnostics._INSTANCE


def emit(event_name, *, level="INFO", result="observed", message=None, **fields):
    instance = recorder()
    if instance is not None:
        instance.record(event_name, dict(level=level, result=result, **fields), message=message)


@contextmanager
def operation(action, *, module="studio", **fields):
    operation_id = "op-" + uuid.uuid4().hex[:16]
    parent = _CONTEXT.get().get("operation_id")
    started = time.perf_counter()
    details = {"action": action, "module": module, "parent_operation_id": parent, **fields}
    with context(operation_id=operation_id, **{k: v for k,v in fields.items() if k in {"project_id", "task_id", "revision_before", "source"}}):
        emit("operation.start", result="started", **details)
        outcome = {"result": "completed"}
        try:
            yield outcome
        except BaseException as exc:
            outcome.update(result="failed", exception=exception_info(exc))
            raise
        finally:
            elapsed = round((time.perf_counter()-started)*1000, 3)
            emit("operation.end", level="ERROR" if outcome["result"] == "failed" else "WARN" if elapsed > 250 else "INFO",
                 **details, **outcome, duration_ms=elapsed, slow=elapsed > 250)


def readable(row):
    return (f"{row['time']} [{row['level']}] {row['message']} · {_ACTIONS.get(row.get('action'),row.get('action') or row['event_name'])} · {_RESULTS.get(row['result'],row['result'])}"
            f" · {row.get('operation_id') or '—'} · {row.get('duration_ms') if row.get('duration_ms') is not None else '—'} ms\n"
            + json.dumps({k:v for k,v in row.items() if k not in {'message','time','level','event_name'}}, ensure_ascii=False, separators=(",", ":")) + "\n")


class EventStore:
    def __init__(self, root, *, capacity=2048, file_bytes=FILE_BYTES):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        salt_path = self.root / ".alias-key"
        try:
            fd = os.open(str(salt_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            salt = salt_path.read_bytes()
            # A peer may have created the file and not yet finished the 32-byte
            # write. Wait only during initialization, never on an event producer.
            for _ in range(10):
                if len(salt)==32:break
                time.sleep(.005);salt=salt_path.read_bytes()
        else:
            salt = secrets.token_bytes(32)
            with os.fdopen(fd, "wb") as stream:
                stream.write(salt)
        if len(salt) != 32:
            raise ValueError("invalid diagnostic alias key")
        self.sanitizer = Sanitizer(salt)
        self.session_id = "session-" + uuid.uuid4().hex
        self.directory = self.root / self.session_id
        self.directory.mkdir()
        self.recent = deque(maxlen=2048)
        self.latencies = deque(maxlen=2048)
        self._pending = deque()
        self._condition = threading.Condition()
        self._capacity = max(8, capacity)
        self.file_bytes = file_bytes
        self._sequence = 0
        self._stop = threading.Event()
        self._finished = False
        self._start = time.perf_counter()
        self._detail_until = 0.0
        self._rates = {}
        try:
            self.inherited_context = json.loads(os.environ.get("TWOBYTEASR_DIAGNOSTIC_PARENT", "{}"))
        except (ValueError, TypeError):
            self.inherited_context = {}
        self.inherited_context = {k:v for k,v in self.inherited_context.items() if k in {"parent_session_id","task_id","operation_id","project_id"}}
        self.losses = Counter()
        self.write_error = None
        self.session = dict(format_version=FORMAT_VERSION, session_id=self.session_id, pid=os.getpid(),
                            started=now(), status="running", previous_exit="unknown")
        self._write_session()
        self.thread = threading.Thread(target=self._write, name="diagnostic-writer", daemon=True)
        self.thread.start()

    @property
    def dropped(self):
        return sum(v for k,v in self.losses.items() if "drop" in k or "failed" in k)

    @dropped.setter
    def dropped(self, value):
        self.losses["legacy_dropped"] = value

    @property
    def detailed(self):
        if self._detail_until and time.monotonic() >= self._detail_until:
            self._detail_until = 0
            self.record("diagnostics.mode", {"result":"completed", "mode":"standard", "reason":"expired"})
        return self._detail_until > 0

    def set_detailed(self, seconds=600):
        self._detail_until = time.monotonic()+min(900,max(0,seconds)) if seconds else 0
        self.record("diagnostics.mode", {"result":"completed", "mode":"detailed" if seconds else "standard", "expires_after_s":min(900,seconds), "content_included":False})

    def _write_session(self):
        target = self.directory / "session.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(self.sanitizer.clean(self.session), ensure_ascii=False, indent=2), encoding="utf8")
        for attempt in range(4):
            try:
                os.replace(temp,target)
                break
            except PermissionError:
                if attempt==3:raise
                time.sleep(.01)

    def record(self, kind, fields, *, message=None):
        try:
            fields = dict(fields)
            if kind in _SAMPLED and not self.detailed:
                stamp = time.monotonic()
                if stamp - self._rates.get(kind, -100) < (5 if kind == "STUDIO_STATE" else 1):
                    self.losses["sampled_events"] += 1
                    return
                self._rates[kind] = stamp
            level = str(fields.pop("level", "ERROR" if any(s in kind.upper() for s in ("EXCEPTION", "FAILED", "FAILURE")) else "WARN" if "STALL" in kind.upper() else "INFO")).upper()
            if level == "DEBUG" and not self.detailed:
                self.losses["debug_not_collected"] += 1
                return
            event_name = str(kind).lower().replace("_", ".")[:100]
            if event_name in {"media", "p74c.t1.media.pool", "media.contract.probe.ready"}:
                if "duration_ms" in fields:
                    fields["media_duration_ms"] = fields.pop("duration_ms")
                for key in ("sample_rate", "channels"):
                    if fields.get(key) == 0:
                        fields[key] = None
            # Errors retain the first few occurrences, then an explicit storm counter.
            if level in {"ERROR", "WARN"}:
                rate_key = (event_name, str(fields.get("error_code", "")))
                stamp, count = self._rates.get(rate_key, (0, 0))
                current = time.monotonic()
                count = count+1 if current-stamp < 1 else 1
                self._rates[rate_key] = (stamp if current-stamp < 1 else current, count)
                if count > 20:
                    self.losses["storm_suppressed"] += 1
                    return
            data = self.sanitizer.clean({**self.inherited_context, **_CONTEXT.get(), **fields})
            # Legacy adapters may supply their own time/kind/sequence. They are
            # payload evidence, never allowed to replace the journal envelope.
            for key in ("format_version", "time", "monotonic_ms", "session_id",
                        "pid", "thread_id", "thread", "sequence", "event_name",
                        "kind", "level", "message"):
                if key in data:
                    data["reported_"+key] = data.pop(key)
            row = dict(format_version=FORMAT_VERSION, time=now(), monotonic_ms=round((time.perf_counter()-self._start)*1000,3),
                       session_id=self.session_id, pid=os.getpid(), thread_id=threading.get_ident(),
                       thread=self.sanitizer.string(threading.current_thread().name), project_id=None, task_id=None, operation_id=None,
                       revision_before=None, revision_after=None, duration_ms=None, source=None, module="legacy", result="observed", **{})
            row.update(data)
            row.update(event_name=event_name, kind=str(kind), level=level,
                       message=self.sanitizer.string(message or _LABELS.get(event_name, "技術狀態記錄")))
            if len(json.dumps(row,ensure_ascii=False).encode("utf8")) > MAX_EVENT_BYTES:
                self.losses["truncated_events"] += 1
                keep = {k:row[k] for k in ("format_version","time","monotonic_ms","session_id","pid","thread_id","thread","event_name","kind","level","message","result","module","project_id","task_id","operation_id","duration_ms","revision_before","revision_after")}
                row = dict(keep, truncated=True, original_fields=list(row)[:64])
            with self._condition:
                self._sequence += 1
                row["sequence"] = self._sequence
                self.recent.append(row)
                if kind == "INPUT_PAINT":
                    self.latencies.append(float(fields.get("total_ms",0)))
                if self._stop.is_set():
                    self.losses["after_close_dropped"] += 1
                    return
                if len(self._pending) >= self._capacity:
                    victim = next((i for i,v in enumerate(self._pending) if isinstance(v,dict) and (v.get("level")=="DEBUG" or v.get("kind") in _SAMPLED)), None)
                    if victim is None and (level in {"WARN","ERROR"} or event_name in _BOUNDARIES):
                        victim = next((i for i,v in enumerate(self._pending) if isinstance(v,dict) and v.get("level")=="INFO" and v.get('event_name') not in _BOUNDARIES),None)
                    if victim is None:
                        self.losses["critical_dropped" if level in {"WARN","ERROR"} or event_name in _BOUNDARIES else "queue_dropped"] += 1
                        return
                    del self._pending[victim]
                    self.losses["evicted_dropped"] += 1
                self._pending.append(row)
                self._condition.notify()
        except Exception:
            self.losses["format_failed"] += 1

    def _rotate(self):
        for stem,suffix in (("events","jsonl"),("readable","log")):
            oldest = self.directory / f"{stem}.{SEGMENTS}.{suffix}"
            if oldest.exists():
                self.losses["rotated_files"] += 1
                self.losses["rotated_bytes"] += oldest.stat().st_size
                oldest.unlink()
            for i in range(SEGMENTS-1, -1, -1):
                old = self.directory / (f"{stem}.{i}.{suffix}" if i else f"{stem}.{suffix}")
                if old.exists():
                    os.replace(old, self.directory / f"{stem}.{i+1}.{suffix}")

    def _read_snapshot(self, cutoff):
        files={}
        for path in self.directory.iterdir():
            if path.name == "session.json" or path.name.startswith("events") and path.suffix == ".jsonl":
                with path.open("rb") as stream:
                    files[path.name] = stream.read(self.file_bytes + MAX_EVENT_BYTES)
        return dict(files=files, cutoff=cutoff, losses=dict(self.losses), write_error=self.write_error)

    def snapshot(self, timeout=8):
        if not self.thread.is_alive():
            return self._read_snapshot(self._sequence)
        done = threading.Event()
        box = {}
        with self._condition:
            if any(isinstance(item, tuple) for item in self._pending):
                raise RuntimeError("diagnostic queue busy; retry export")
            self._pending.append((done,box,self._sequence))
            self._condition.notify()
        if not done.wait(timeout):
            raise TimeoutError("diagnostic snapshot barrier timed out")
        if "error" in box:
            raise OSError(box["error"])
        return box["snapshot"]

    def _write(self):
        stream = human = None
        try:
            while True:
                with self._condition:
                    if not self._pending and not self._stop.is_set():
                        self._condition.wait(.2)
                    item = self._pending.popleft() if self._pending else None
                if item is None:
                    if stream: stream.flush()
                    if human: human.flush()
                    if self._stop.is_set(): break
                    continue
                if isinstance(item,tuple):
                    done,box,cutoff=item
                    try:
                        if stream: stream.flush()
                        if human: human.flush()
                        self.session.update(losses=dict(self.losses), write_error=self.write_error)
                        self._write_session()
                        box["snapshot"] = self._read_snapshot(cutoff)
                    except Exception as exc:
                        box["error"] = type(exc).__name__
                    finally:
                        done.set()
                    continue
                try:
                    if stream is None:
                        stream = (self.directory/"events.jsonl").open("a",encoding="utf8")
                        human = (self.directory/"readable.log").open("a",encoding="utf8")
                    if stream.tell() >= self.file_bytes or human.tell() >= self.file_bytes:
                        stream.close(); human.close(); stream=human=None
                        self._rotate()
                        stream = (self.directory/"events.jsonl").open("a",encoding="utf8")
                        human = (self.directory/"readable.log").open("a",encoding="utf8")
                    stream.write(json.dumps(item,ensure_ascii=False,separators=(",", ":"))+"\n")
                    human.write(readable(item))
                    # Bounded latency, no GUI IO. Error boundaries flush immediately.
                    if item["level"] in {"WARN","ERROR"} or item["result"] in {"completed","failed"}:
                        stream.flush(); human.flush()
                except Exception as exc:
                    self.write_error = type(exc).__name__
                    self.losses["write_failed"] += 1
                    for handle in (stream,human):
                        try:
                            if handle: handle.close()
                        except OSError: pass
                    stream=human=None
        except Exception as exc:
            self.write_error=type(exc).__name__
            self.losses["writer_failed"] += 1
        finally:
            for handle in (stream,human):
                try:
                    if handle: handle.close()
                except OSError: pass

    def close_store(self, *, clean=False, timeout=2):
        self.record("session.end", dict(result="completed" if clean else "failed", clean=clean, losses=dict(self.losses)))
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        self.thread.join(timeout)
        self.session.update(status="clean" if clean and not self.thread.is_alive() else "not_cleanly_ended",
                            ended=now(), losses=dict(self.losses), write_error=self.write_error,
                            shutdown_timeout=self.thread.is_alive())
        try: self._write_session()
        except OSError: pass


class DiagnosticLogHandler(logging.Handler):
    """Default evidence without leaking interpolated subtitle/prompt strings."""
    def emit(self, record):
        try:
            fields = dict(module=record.name, level=record.levelname, source="python.logging",
                          log_line=record.lineno, log_function=record.funcName,
                          message_chars=len(str(record.msg)), formatted_message_included=False)
            if record.exc_info and record.exc_info[1]:
                fields["exception"] = exception_info(record.exc_info[1])
            emit("python.log", **fields)
        except Exception:
            pass


def install_asyncio(loop):
    """Explicit per-loop hook; preserves any installed/default exception handler."""
    previous=loop.get_exception_handler()
    def handler(active, details):
        exc=details.get("exception")
        emit("async.exception",level="ERROR",result="failed",exception=exception_info(exc) if exc else None)
        if previous: previous(active,details)
        else: active.default_exception_handler(details)
    loop.set_exception_handler(handler)
    return handler
