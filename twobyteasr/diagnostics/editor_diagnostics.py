"""Bounded local diagnostic sessions. Never records subtitle text or uploads."""
from __future__ import annotations
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import faulthandler
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import queue
import re
import sys
import threading
import time
import traceback
import uuid
import zipfile

MAX_BYTES = 2 * 1024 * 1024
MAX_SESSIONS = 8
MAX_RECORDING_SECONDS = 600
_INSTANCE = None
_INSTALL_ERROR = None
import weakref
_PAGES = weakref.WeakSet()

def register_page(page):
    _PAGES.add(page)

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

def safe(value, key=""):
    from .event_log import Sanitizer
    sanitizer = _INSTANCE.sanitizer if _INSTANCE is not None else Sanitizer()
    return sanitizer.clean(value, key)


def safe_text(value):
    """Keep a text, with its paths, keys, URLs and e-mails redacted.

    For texts the record needs to stay readable (a failure reason, a command
    the caller already chose to log); `safe` drops such fields entirely.
    """
    from .event_log import Sanitizer
    sanitizer = _INSTANCE.sanitizer if _INSTANCE is not None else Sanitizer()
    return sanitizer.string(value)


def stack_frames(tb):
    return [f"{Path(f.filename).name}:{f.lineno}:{f.name}"
            for f in traceback.extract_tb(tb)[-24:]] if tb else []

def root_dir():
    from ..runtime_paths import user_data_root
    return user_data_root() / "logs" / "diagnostic-sessions"

def record(kind, /, **fields):
    instance = _INSTANCE
    if instance is not None:
        instance.record(kind, fields)


def recording_active():
    return _INSTANCE is not None and _INSTANCE.recording

@contextmanager
def measure(kind):
    start = time.perf_counter()
    try:
        yield
    finally:
        record(kind, duration_ms=round((time.perf_counter()-start)*1000, 3))

def latency_stats(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    def at(p):
        return round(values[min(len(values)-1, max(0, __import__("math").ceil(len(values)*p)-1))], 3)
    return dict(count=len(values), p50_ms=at(.5), p95_ms=at(.95),
                p99_ms=at(.99), max_ms=at(1), over_100_ms=sum(v>100 for v in values),
                over_200_ms=sum(v>200 for v in values), over_250_ms=sum(v>250 for v in values),
                over_500_ms=sum(v>500 for v in values))

def _session_process_alive(row):
    """An exited Windows process can retain a queryable creation time."""
    import psutil
    try:
        process = psutil.Process(int(row["pid"]))
        started = datetime.fromisoformat(row["started"]).timestamp()
        return process.is_running() and abs(process.create_time()-started) < 30
    except (psutil.Error, ValueError, KeyError):
        return False

from .event_log import EventStore, exception_info


class Recorder(EventStore):
    def __init__(self, root):
        super().__init__(root)
        self.session.update(platform=platform.platform(), python=sys.version.split()[0],
                            architecture=platform.machine(), frozen=bool(getattr(sys, "frozen", False)),
                            entry=Path(sys.argv[0]).name)
        self.recording_id = uuid.uuid4().hex[:12]
        try:
            from .build_identity import load_build_identity
            build = load_build_identity()
            self.session["build"] = dict(version=build.app_version, channel=build.build_channel,
                built=build.build_time, commit=build.git_sha, dirty=build.git_dirty,
                source_sha256=build.source_sha256)
        except Exception:
            self.session["build"] = "unknown"
        self._write_session()
        self.record("session.start", dict(result="started", build=self.session["build"], entry=self.session["entry"]))
        self.fault_file = open(self.directory/"native-fault.txt", "wb", buffering=0)
        faulthandler.enable(file=self.fault_file, all_threads=True)
        self._old_sys_hook = sys.excepthook
        self._old_thread_hook = threading.excepthook
        self._old_unraisable = sys.unraisablehook
        def exception(kind, value, tb):
            self.record("PYTHON_EXCEPTION", dict(result="failed", exception=exception_info(value)))
            self._old_sys_hook(kind, value, tb)
        def thread_exception(args):
            self.record("THREAD_EXCEPTION", dict(result="failed", exception=exception_info(args.exc_value)))
            self._old_thread_hook(args)
        def unraisable(args):
            self.record("UNRAISABLE_EXCEPTION", dict(result="failed", exception=exception_info(args.exc_value)))
            self._old_unraisable(args)
        sys.excepthook, threading.excepthook, sys.unraisablehook = exception, thread_exception, unraisable
        self._installed_hooks = (exception, thread_exception, unraisable)
        import logging
        from .event_log import DiagnosticLogHandler
        self.log_handler = DiagnosticLogHandler(level=logging.WARNING)
        logging.getLogger().addHandler(self.log_handler)
        import gc
        gc_started = {}
        def gc_event(phase, info):
            identity = (threading.get_ident(), info.get("generation", -1))
            if phase == "start":
                gc_started[identity] = time.perf_counter()
            else:
                elapsed = (time.perf_counter()-gc_started.pop(identity, time.perf_counter()))*1000
                if elapsed >= 20:
                    self.record("GC_PAUSE", dict(duration_ms=round(elapsed, 3), generation=identity[1],
                        thread=threading.current_thread().name, collected=info.get("collected", 0)))
        self.gc_callback = gc_event
        gc.callbacks.append(gc_event)
        self.environment_timer = threading.Timer(4, self._environment)
        self.environment_timer.daemon = True
        self.environment_timer.start()
        threading.Thread(target=self._resources, name="diagnostic-resources", daemon=True).start()

    @property
    def standard_recording(self):
        return not self._finished

    @property
    def recording(self):
        # Compatibility for the old bounded input/resource recorder. Standard
        # operation/error events remain enabled when detailed capture expires.
        return not self._finished and self.detailed

    def start_recording(self):
        if self._finished:
            return
        self.recording_id = uuid.uuid4().hex[:12]
        self.latencies.clear()
        self.set_detailed(MAX_RECORDING_SECONDS)
        self.record("RECORDING_START", dict(limit_seconds=MAX_RECORDING_SECONDS,
                                          recording_id=self.recording_id))

    def stop_recording(self):
        self.record("RECORDING_STOP", dict(latency=latency_stats(self.latencies),
                                         recording_id=self.recording_id))
        self.set_detailed(0)

    def _resources(self):
        # Process counters, never Qt or project objects; no command lines or
        # private file names. CPU values are cumulative seconds, not percent.
        import psutil
        from ..system.process_snapshot import process_snapshot, descendant_pids
        process = psutil.Process()
        last_sample = 0.0
        while not self._stop.wait(2):
            stamp = time.monotonic()
            if stamp-last_sample < (2 if self.recording else 30):
                continue
            last_sample = stamp
            rows = []
            started = time.perf_counter()
            try:
                census = process_snapshot()
                children = descendant_pids(process.pid, census)
                for pid in [process.pid, *children[:63]]:
                    try:
                        child = psutil.Process(pid)
                        with child.oneshot():
                            cpu = child.cpu_times()
                            io = child.io_counters() if hasattr(child, 'io_counters') else None
                            rows.append(dict(pid=child.pid, role='main' if child.pid == process.pid else 'child',
                                cpu_s=round(cpu.user+cpu.system, 4), rss_bytes=child.memory_info().rss,
                                threads=census.get(pid, (None, None))[1], handles=child.num_handles() if os.name == 'nt' else None,
                                read_bytes=io.read_bytes if io else None, write_bytes=io.write_bytes if io else None))
                    except (psutil.Error, OSError, NotImplementedError):
                        continue
                self.record('RESOURCES', dict(processes=rows, child_count=len(children),
                    collector_ms=(time.perf_counter()-started)*1000,
                    truncated=len(children)>63, log_queue=len(self._pending)))
            except (psutil.Error, OSError):
                continue


    def _environment(self):
        if self._finished:
            return
        try:
            import psutil
            previous = []
            inactive = []
            for directory in sorted(self.root.iterdir()):
                path = directory/"session.json"
                if directory == self.directory or not path.is_file():
                    continue
                try:
                    row = json.loads(path.read_text("utf8"))
                    alive = _session_process_alive(row)
                    status = row.get("status", "unknown")
                    if status == "running" and not alive:
                        status = "previous_not_cleanly_ended"
                    previous.append(dict(status=status, started=row.get("started"), build=row.get("build")))
                    if not alive: inactive.append(directory)
                except (ValueError, OSError):
                    pass
            self.record("PREVIOUS_SESSIONS", dict(sessions=previous[-8:]))
            self.record("HOST", dict(cpu=platform.processor(), logical_cpus=os.cpu_count(),
                ram_gb=round(psutil.virtual_memory().total/1024**3, 1)))
            self.record("MODULES", dict(modules=module_inventory(os.getpid())))
            if sys.platform == "win32":
                from ..system.processes import run_hidden_subprocess
                result = run_hidden_subprocess(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,VideoProcessor,CurrentRefreshRate | ConvertTo-Json -Compress"],
                    purpose="diagnostic graphics inventory", capture_output=True, timeout=15)
                try:
                    graphics = json.loads(result.stdout.decode("utf8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout)
                except (TypeError, ValueError):
                    graphics = "unknown"
                self.record("GRAPHICS", dict(adapters=graphics))
            from .support_bundle import maintain_sessions
            self.record("diagnostics.retention", maintain_sessions(self.root, current=self.directory))
        except Exception as exc:
            self.record("ENVIRONMENT_UNAVAILABLE", dict(exception=type(exc).__name__))

    def finish(self, *, clean=False):
        if self._finished:
            return
        self._finished = True
        self.environment_timer.cancel()
        import gc
        if self.gc_callback in gc.callbacks: gc.callbacks.remove(self.gc_callback)
        self.close_store(clean=clean)
        import logging
        logging.getLogger().removeHandler(self.log_handler)
        if (sys.excepthook, threading.excepthook, sys.unraisablehook) == self._installed_hooks:
            sys.excepthook, threading.excepthook, sys.unraisablehook = self._old_sys_hook, self._old_thread_hook, self._old_unraisable


def module_inventory(pid):
    """Actual loaded modules, path class and SHA; no full private path."""
    import psutil
    rows=[]
    app_root=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[2]
    wanted = re.compile(r"(?i)(python3\d*|pyside|shiboken|qt6|mpv|libmpv|vulkan|d3d11|dxgi|nv.*|igd.*|atio.*).*\.(dll|pyd|exe)$")
    for mapping in psutil.Process(pid).memory_maps():
        p=Path(mapping.path)
        if not wanted.match(p.name) or len(rows)>=48:
            continue
        try:
            with p.open("rb") as stream:
                h=hashlib.sha256()
                for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
            origin="application" if p.is_relative_to(app_root) else ("windows" if "windows" in str(p).lower() else "other")
            rows.append(dict(name=p.name, origin=origin, version=file_version(p), size=p.stat().st_size, sha256=h.hexdigest()))
        except OSError:
            rows.append(dict(name=p.name, origin="unknown", sha256="unknown"))
    return rows

def file_version(path):
    if sys.platform != "win32": return "unknown"
    try:
        import ctypes
        from ctypes import wintypes
        dll=ctypes.WinDLL("version")
        dll.GetFileVersionInfoSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
        dll.GetFileVersionInfoW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]
        dll.VerQueryValueW.argtypes=[wintypes.LPCVOID,wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.UINT)]
        size=dll.GetFileVersionInfoSizeW(str(path),None)
        if not size:return "unknown"
        data=ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(path),0,size,data):return "unknown"
        pointer=ctypes.c_void_p();length=wintypes.UINT()
        if not dll.VerQueryValueW(data,"\\",ctypes.byref(pointer),ctypes.byref(length)):return "unknown"
        words=ctypes.cast(pointer,ctypes.POINTER(wintypes.DWORD))
        return ".".join(str(v) for v in (words[2]>>16,words[2]&65535,words[3]>>16,words[3]&65535))
    except (OSError,ValueError,AttributeError):return "unknown"

def media_inventory(path):
    # Once per opened source, off the GUI thread; reuse the metadata cache.
    try:
        from ..media.media_service import GLOBAL_MEDIA_SERVICE
        value=GLOBAL_MEDIA_SERVICE.metadata(path).to_dict()
        fields=("duration_ms","has_video","has_audio","video_codec","audio_codec","width","height",
                "fps","video_timebase","audio_timebase","sample_rate","channels","source_size")
        record("MEDIA", **{key:value.get(key,"unknown") for key in fields},
               container=Path(path).suffix.lower(), variable_frame_rate="unknown",
               variable_frame_rate_note="Full frame timestamps not scanned by lightweight diagnostics")
    except Exception as exc:record("MEDIA_UNAVAILABLE",exception=type(exc).__name__)


def install_early():
    global _INSTANCE, _INSTALL_ERROR
    if os.environ.get('TWOBYTEASR_EDITOR_DIAGNOSTICS', '1').lower() in {'0', 'false', 'off'}:
        return None
    if _INSTANCE is None:
        try:
            _INSTANCE=Recorder(root_dir())
        except Exception as exc:
            _INSTALL_ERROR=type(exc).__name__
            try:
                import tempfile
                _INSTANCE=Recorder(Path(tempfile.gettempdir())/"2ByteASR-diagnostic-fallback")
                _INSTANCE.session["fallback_location"] = True
                _INSTANCE.record("diagnostics.fallback",dict(level="WARN",result="partial",error_code=_INSTALL_ERROR))
            except Exception:
                pass
    return _INSTANCE


def install_worker():
    """Opt-in child session; no GPU/module inventory or Qt import in workers."""
    global _INSTANCE
    if _INSTANCE is not None or not os.environ.get('TWOBYTEASR_DIAGNOSTIC_PARENT'):
        return _INSTANCE
    try:
        import atexit
        _INSTANCE=EventStore(root_dir())
        _INSTANCE.session.update(entry=Path(sys.argv[0]).name,role='worker',parent_session_id=_INSTANCE.inherited_context.get('parent_session_id'))
        _INSTANCE.record('session.start',dict(result='started',role='worker'))
        atexit.register(lambda:_INSTANCE.close_store(clean=True))
    except Exception:
        _INSTANCE=None
    return _INSTANCE

def install_gui(app):
    instance=install_early()
    if instance is None:
        if not getattr(app,'_diagnostics_unavailable_notified',False):
            app._diagnostics_unavailable_notified=True
            from PySide6.QtWidgets import QMessageBox
            from ..i18n import tr
            box=QMessageBox(QMessageBox.Icon.Warning,tr('诊断记录暂不可用'),
                tr('诊断目录与系统临时目录都无法写入。请释放磁盘空间或修正权限后重新打开程序；工程仍可操作，但这次可能缺少诊断数据。'))
            box.show();app._diagnostics_unavailable_notice=box
        return
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QObject, QTimer, qVersion, qInstallMessageHandler
    record("QT", pyside=pyside_version, qt=qVersion())
    record("SCREENS", screens=[dict(size=[s.size().width(),s.size().height()],
        refresh_hz=s.refreshRate(), dpi=s.logicalDotsPerInch(), scale=s.devicePixelRatio(),
        geometry=[s.geometry().x(),s.geometry().y(),s.geometry().width(),s.geometry().height()])
        for s in app.screens()])
    def qt_message(kind, context, message):
        record("QT_MESSAGE", severity=int(kind.value), category=context.category or "",
               level="ERROR" if int(kind.value) in (2,3) else "WARN" if int(kind.value)==1 else "DEBUG",
               location=Path(context.file or "").name, line=context.line,
               signature=instance.sanitizer.alias(message,"fingerprint"), message_characters=len(message))
        if instance.previous_qt_handler is not None:
            instance.previous_qt_handler(kind,context,message)
    instance.qt_handler = qt_message
    instance.previous_qt_handler=qInstallMessageHandler(qt_message)
    timer=QTimer(app);timer.setInterval(2000)
    seen=set()
    media_seen=set()
    record("PLAYER_REQUEST", vo=os.environ.get("TWOBYTEASR_DIAGNOSTIC_VO","gpu-next"),
           hwdec=os.environ.get("TWOBYTEASR_DIAGNOSTIC_HWDEC","auto-safe"),
           no_player=os.environ.get("TWOBYTEASR_DIAGNOSTIC_NO_PLAYER")=="1",
           no_edit_preview=os.environ.get("TWOBYTEASR_DIAGNOSTIC_NO_EDIT_PREVIEW")=="1")
    def sample():
        if (_INSTALL_ERROR or instance.write_error) and not getattr(instance,"warned_write",False):
            instance.warned_write=True
            from PySide6.QtWidgets import QMessageBox
            from ..i18n import tr
            box=QMessageBox(QMessageBox.Icon.Warning,tr("诊断记录暂不可用"),
                tr("诊断数据未能写入原位置，目前暂存在系统临时文件夹。请检查磁盘空间与权限；可从「回报问题」选择其他文件夹导出。")
                if _INSTALL_ERROR and instance else
                tr("诊断数据未能写入原位置。请检查磁盘空间与权限；可从「回报问题」选择其他文件夹导出。"))
            box.setStandardButtons(QMessageBox.StandardButton.Ok);box.show();instance.write_notice=box
        stamp = time.monotonic()
        if not instance.recording and stamp < getattr(instance, "_next_state_sample", 0):
            return
        instance._next_state_sample = stamp + (0 if instance.recording else 5)
        for page in list(_PAGES):
            if page is None or getattr(page,"_close_requested",False):
                continue
            project=page.project
            if project is None: continue
            if project.media.path and project.media.path not in media_seen:
                if len(media_seen)>=64:media_seen.clear()
                media_seen.add(project.media.path)
                threading.Thread(target=media_inventory,args=(project.media.path,),daemon=True).start()
                record("PROJECT_SCALE", cues=len(project.cues),
                       word_items=sum(len(row.get("words",[])) for row in project.asr_evidence.values() if isinstance(row,dict)),
                       speakers=len(project.speakers),
                       video_tracks=len(project.video_tracks), audio_tracks=len(project.audio_tracks),
                       caption_tracks="unknown")
            video=page.video;controller=video.controller
            props=controller.observed_properties() if controller else {}
            from ..studio.studio_performance import _gui_loop_stats
            ass_actor = getattr(page, '_ass_actor', None)
            record("STUDIO_STATE", cues=len(project.cues), speakers=len(project.speakers),
                project_id=project.project_id,
                revision=getattr(getattr(project,'_studio_state_runtime',None),'revision',None),
                ass_generation=page._ass_generation,
                preview_busy=page._ass_worker_running,
                preview=ass_actor.diagnostic_state() if ass_actor is not None else {},
                qc_pending=len(getattr(page,'_pending_qc_cue_ids',())),
                loop=_gui_loop_stats(),
                word_evidence_rows=len(project.asr_evidence), editing=bool(getattr(page,"_canvas_editor",None)),
                paused=bool(video._paused), seeking=bool(props.get("seeking",False)),
                pending=controller.actor_status() if controller else {}, autosave_busy=page._autosave_worker_running,
                media=dict(width=project.media.width,height=project.media.height,duration_ms=project.media.duration_ms),
                player={k:props.get(k,"unknown") for k in ("video-codec","hwdec-current","current-vo","display-fps",
                    "estimated-display-fps","container-fps","video-sync","mpv-version","video-params",
                    "decoder-frame-drop-count","frame-drop-count","vo-delayed-frame-count")})
            pid=getattr(getattr(controller,"_process",None),"pid",None)
            if pid and pid not in seen:
                seen.add(pid)
                def modules(target=pid):
                    try: record("PLAYER_MODULES", modules=module_inventory(target))
                    except Exception as exc: record("PLAYER_MODULES_UNAVAILABLE", exception=type(exc).__name__)
                threading.Thread(target=modules,daemon=True).start()
    timer.timeout.connect(sample);timer.start();instance.timer=timer

def export_bundle(target, *, include_dumps=False, root=None, **options):
    """Compatibility entry; the support exporter owns the consistent snapshot."""
    from .support_bundle import export_report
    if include_dumps:
        raise ValueError("Raw memory dumps may contain credentials; share them separately after private review")
    return export_report(target, root=Path(root) if root else root_dir(), instance=_INSTANCE, **options)
