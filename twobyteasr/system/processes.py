"""Cross-platform subprocess launch and termination helpers."""

from __future__ import annotations

import os
import ctypes
import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


_instrumentation_lock = threading.Lock()
_action_context = threading.local()
_child_start_count = 0


def child_process_start_count() -> int:
    """Monotonic count of children launched through the canonical wrappers."""
    with _instrumentation_lock:
        return int(_child_start_count)


def _note_child_start() -> int:
    global _child_start_count
    with _instrumentation_lock:
        _child_start_count += 1
        return int(_child_start_count)


@contextmanager
def process_action_scope(action_id: str):
    """Attach a stable user-action id to child-process diagnostics."""
    previous = getattr(_action_context, "action_id", "")
    _action_context.action_id = str(action_id or "")
    try:
        yield
    finally:
        _action_context.action_id = previous


def _descendant_snapshot(pid: int | None) -> list[dict[str, object]]:
    if not pid:
        return []
    try:
        import psutil

        return [
            {
                "pid": int(child.pid),
                "name": str(child.name()),
                "command": list(child.cmdline()),
            }
            for child in psutil.Process(int(pid)).children(recursive=True)
        ]
    except Exception:
        return []


def canonical_subprocess_command(
    command: Iterable[object],
    *,
    environ: dict[str, str] | None = None,
) -> list[object]:
    """Return the one Windows-safe command shape used by every launcher.

    ``CreateProcess`` cannot execute batch files directly.  Letting Python or
    Windows infer a shell for ``.cmd``/``.bat`` leaves the console creation
    policy ambiguous and was the source of descendant ``cmd.exe`` flashes in
    the packaged GUI.  Resolve the command interpreter explicitly so the same
    hidden creation flags apply to the shell and everything it starts.
    """
    command_list = list(command)
    if os.name != "nt" or not command_list:
        return command_list
    executable = str(command_list[0] or "")
    if Path(executable).suffix.casefold() not in {".cmd", ".bat"}:
        return command_list
    env = environ if environ is not None else os.environ
    comspec = str(env.get("COMSPEC") or "").strip()
    if not comspec:
        system_root = str(env.get("SystemRoot") or r"C:\Windows")
        comspec = str(Path(system_root) / "System32" / "cmd.exe")
    return [comspec, "/d", "/s", "/c", *command_list]


def main_python_executable(project_root: str | os.PathLike[str] | None = None) -> str:
    """Return a real Python interpreter, never the frozen GUI executable.

    Resolution goes through the RuntimeEnvironmentRegistry so a packaged exe
    reuses the registered/legacy main venv instead of expecting one inside
    the install directory. The historical exe-dir candidate remains the last
    fallback for installs that really do ship their own venv.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    try:
        from twobyteasr.system.runtime_registry import resolve_runtime_python

        resolved = resolve_runtime_python("main")
        if resolved:
            return resolved
    except Exception:
        pass
    override = str(os.environ.get("TWOBYTEASR_MAIN_PYTHON") or "").strip()
    if override and Path(override).is_file():
        from ..python_runtime_identity import python_entry_path
        return python_entry_path(override)
    root = Path(project_root) if project_root else Path(sys.executable).resolve().parent
    candidate = root / ".venv-main" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    from ..python_runtime_identity import python_entry_path
    return python_entry_path(candidate) if candidate.is_file() else ""


def hidden_subprocess_kwargs() -> dict:
    """Prevent console executables from opening a stray window on Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def sanitized_child_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Child env without frozen-Python leftovers (P8C-R3.1).

    A PyInstaller parent carries its own bundle directory at the FRONT of
    PATH (bootloader behavior) plus potentially PYTHONHOME/PYTHONPATH/
    _MEIPASS2. Any EXTERNAL python spawned from it (role venv probes,
    MOSS/FireRed workers) then loads the bundle's python3.dll/python310.dll
    and dies with "Module use of python310.dll conflicts". Non-Python
    children ignore these variables, so cleaning every hidden child is safe.
    """
    child = dict(os.environ if env is None else env)
    for key in ("PYTHONHOME", "PYTHONPATH", "_MEIPASS2"):
        child.pop(key, None)
    if getattr(sys, "frozen", False):
        bundle = os.path.normcase(
            os.path.dirname(os.path.abspath(sys.executable))
        )
        parts = [
            part
            for part in child.get("PATH", "").split(os.pathsep)
            if part and os.path.normcase(os.path.abspath(part)) != bundle
        ]
        child["PATH"] = os.pathsep.join(parts)
    return child


def external_python_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Clean only an external Python child; keep intentional app-child routes."""
    child = sanitized_child_environment(env)
    for key in tuple(child):
        if key.upper().startswith(('CONDA_', 'PIP_', 'UV_')):
            child.pop(key, None)
    child.update(PYTHONNOUSERSITE='1', PIP_CONFIG_FILE=os.devnull)
    for key in tuple(child):
        if key.startswith("_PYI") or key in {"__PYVENV_LAUNCHER__", "VIRTUAL_ENV",
                                            "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"}:
            child.pop(key, None)
    for key in ("DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LD_LIBRARY_PATH"):
        original = child.pop(key + "_ORIG", None)
        if original is None:
            child.pop(key, None)
        else:
            child[key] = original
    child.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return child


def utf8_worker_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Child env that makes a NON-isolated Python child speak UTF-8.

    Children started without ``-I`` honor ``PYTHONIOENCODING``/``PYTHONUTF8``;
    setting them explicitly means we never depend on the machine-level
    environment (a clean Windows install has neither, and ACP=936 machines
    then emit GBK into a pipe the parent decodes as UTF-8).
    """
    child = external_python_environment(env)
    child["PYTHONIOENCODING"] = "utf-8"
    child["PYTHONUTF8"] = "1"
    return child


def python_utf8_command(command: Iterable[object]) -> list:
    """Insert ``-X utf8`` behind the interpreter of a Python child command.

    ``-I`` (isolated mode) implies ``-E`` and therefore IGNORES every
    ``PYTHON*`` environment variable: on an ANSI-936 Windows the piped child
    defaults its stdout to GBK while the parent decodes UTF-8, turning all
    Chinese worker progress into U+FFFD (2026-09-20 MOSS log mojibake).
    ``-X utf8`` is an explicit interpreter option and survives isolation,
    so isolated workers MUST get their stdio pinned through argv.
    """
    args = [str(item) for item in command]
    for index, token in enumerate(args):
        if token == "-I":
            args[index + 1 : index + 1] = ["-X", "utf8"]
            return args
    args[1:1] = ["-X", "utf8"]
    return args


def run_speaker_embed_worker(
    *,
    worker_path: str,
    main_python: str,
    manifest: dict,
    cancel_check=None,
) -> dict:
    """Run speaker_embed_worker.py in the main runtime venv (P8C-R3.1).

    Frozen GUIs have no torch; ECAPA speaker embeddings are computed by this
    subprocess against the cached unified audio and returned as
    {\"chunk|speaker\": [floats]}. Fixed argv, no shell.
    """
    import json
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ecapa_embed_") as folder:
        work_dir = Path(folder).resolve()
        manifest_path = work_dir / "manifest.json"
        output_path = work_dir / "embeddings.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        command = python_utf8_command([
            os.path.abspath(os.fspath(main_python)), "-B", "-I", str(Path(worker_path).resolve()),
            "--manifest", str(manifest_path), "--output", str(output_path),
        ])
        options = dict(purpose="ECAPA speaker embeddings", text=True, encoding="utf-8", errors="replace",
                       cwd=str(Path(os.path.abspath(os.fspath(main_python))).parent),
                       env=utf8_worker_environment(), shell=False)
        if cancel_check is None:
            completed = run_hidden_subprocess(command, capture_output=True, timeout=900, **options)
            stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
        else:
            process = popen_hidden_subprocess(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
            deadline = time.monotonic() + 900
            try:
                while True:
                    try:
                        stdout, stderr = process.communicate(timeout=.2)
                        code = process.returncode
                        break
                    except subprocess.TimeoutExpired:
                        if cancel_check():
                            from ..recognition.service import CancelledError
                            raise CancelledError('声纹分析已取消')
                        if time.monotonic() >= deadline:
                            raise RuntimeError('声纹分析超时')
            finally:
                if process.poll() is None:
                    stop_process_tree(process)
        tail = ((stderr or "") + (stdout or ""))[-600:]
        if code != 0 or not output_path.is_file():
            raise RuntimeError(f"ECAPA 声纹子进程失败：{tail}")
        return json.loads(output_path.read_text(encoding="utf-8"))


def _hidden_launch(options: dict[str, Any]) -> bool:
    if os.name != "nt":
        return True
    return bool(options.get("creationflags")) and bool(
        getattr(options.get("startupinfo"), "dwFlags", 0)
    )


def _window_snapshot(pid: int | None) -> list[dict[str, object]]:
    """Best-effort top-level HWND snapshot for diagnostics only."""
    if os.name != "nt":
        return []
    windows: list[dict[str, object]] = []
    try:
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32=ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowTextLengthW.argtypes=[ctypes.c_void_p]
        user32.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
        user32.IsWindowVisible.argtypes=[ctypes.c_void_p]

        def visit(hwnd, _lparam):
            owner = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if pid and owner.value != int(pid):
                return True
            length = int(ctypes.windll.user32.GetWindowTextLengthW(hwnd))
            buffer = ctypes.create_unicode_buffer(max(1, length + 1))
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
            windows.append({
                "hwnd": int(hwnd),
                "title": buffer.value,
                "visible": bool(ctypes.windll.user32.IsWindowVisible(hwnd)),
                "pid": int(owner.value),
            })
            return True

        ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
    except (AttributeError, OSError, ValueError):
        return []
    return windows


def _record_child_process(
    command: Iterable[object],
    purpose: str,
    *,
    started: float,
    hidden: bool,
    returncode: int | None,
    child_pid: int | None = None,
    phase: str = "exit",
    creationflags: int = 0,
    original_command: Iterable[object] | None = None,
    redact_process_details: bool = False,
    diagnostic_context: dict | None = None,
) -> None:
    from ..diagnostics.process_diagnostics import record_process, _safe_command
    command_list = list(command)
    original_list = list(original_command) if original_command is not None else command_list
    binary = str(command_list[0]) if command_list else ""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "phase": str(phase),
        "parent_pid": os.getpid(),
        "root_pid": os.getpid(),
        "child_pid": int(child_pid) if child_pid else None,
        "action_id": str(getattr(_action_context, "action_id", "") or purpose),
        "binary": Path(binary).name or binary,
        "executable": binary,
        "command": _safe_command(command_list),
        "original_command": _safe_command(original_list),
        "purpose": str(purpose),
        "hidden": bool(hidden),
        "creationflags": int(creationflags or 0),
        "duration_ms": round(max(0.0, time.perf_counter() - started) * 1000, 1),
        "returncode": returncode,
        "thread": threading.current_thread().name,
        "redacted_details": bool(redact_process_details),
        "windows": [],
        "descendants": [],
    }
    from ..diagnostics.event_log import emit
    from ..diagnostics.event_bridge import runtime_context_fields
    emit("process.start" if phase=="start" else "process.end", module="processes",
         result="started" if phase=="start" else "completed" if returncode==0 else "failed" if returncode is not None else "unknown",
         level="ERROR" if phase=="exit" and returncode not in (0,None) else "INFO",
         child_pid=child_pid, child_operation_id=f"child-{os.getpid()}-{child_pid}-{int(started*1000)}",
         executable_path=binary, purpose=purpose, duration_ms=payload["duration_ms"],exit_code=returncode,
         argument_count=max(0,len(command_list)-1),hidden=hidden, **(diagnostic_context if diagnostic_context is not None else runtime_context_fields()))
    record_process(payload)


def renderer_node_command(renderer_root, *arguments):
    """Only the application's private Node may run rendering code."""
    root=Path(renderer_root).resolve()
    node=root.parent/'tools'/'node'/('node.exe' if os.name=='nt' else 'node')
    if not node.is_file() or node.stat().st_size<1024:
        raise RuntimeError(f'程序自带 Node Runtime 缺失或损坏：{node}；请修复安装后重试预览')
    policy=root/'process_policy.cjs'
    if not policy.is_file():raise RuntimeError(f'渲染进程启动策略缺失：{policy}')
    return [str(node),'--require',str(policy),*map(str,arguments)]


def renderer_child_environment():
    from ..diagnostics.process_diagnostics import process_log_path
    env=sanitized_child_environment()
    for name in ('NODE_OPTIONS','NODE_PATH','ELECTRON_RUN_AS_NODE'):env.pop(name,None)
    env['TWOBYTEASR_CHILD_PROCESS_LOG']=str(process_log_path())
    env['TWOBYTEASR_PROCESS_ACTION']='web-subtitle-render'
    from ..exports.export_run_log import current_export_log
    logger = current_export_log()
    if logger is not None:
        env['TWOBYTEASR_CHILD_PROCESS_LOG'] = str(logger.path / 'renderer-children.jsonl')
        env['TWOBYTEASR_EXPORT_JOB_ID'] = str(logger.job.export_context['job_id'])
        env['TWOBYTEASR_EXPORT_STDERR_ROOT'] = str(logger.path)
    return env


def run_hidden_subprocess(
    command: Iterable[object],
    *,
    purpose: str,
    runner: Callable[..., Any] | None = None,
    **kwargs,
):
    """Run a console child without a Windows window and optionally log it."""
    original_command = list(command)
    command_list = canonical_subprocess_command(
        original_command,
        environ=kwargs.get("env"),
    )
    if kwargs.get("env") is None:
        kwargs["env"] = sanitized_child_environment()
    from ..diagnostics.event_log import recorder
    from ..diagnostics.event_bridge import runtime_context_fields
    diagnostic = recorder()
    if diagnostic is not None:
        import json
        kwargs["env"] = dict(kwargs.get("env") or os.environ)
        kwargs["env"]["TWOBYTEASR_DIAGNOSTIC_PARENT"] = json.dumps({"parent_session_id":diagnostic.session_id,**runtime_context_fields()})
    options = hidden_subprocess_kwargs()
    for key, value in options.items():
        kwargs.setdefault(key, value)
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    if not kwargs.get("capture_output"):
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.DEVNULL)
    started = time.perf_counter()
    completed = None
    child_pid = None
    export_log = None
    try:
        if runner is not None:
            completed = runner(command_list, **kwargs)
        else:
            input_value = kwargs.pop("input", None)
            capture_output = bool(kwargs.pop("capture_output", False))
            timeout = kwargs.pop("timeout", None)
            check = bool(kwargs.pop("check", False))
            if capture_output:
                kwargs["stdout"] = subprocess.PIPE
                kwargs["stderr"] = subprocess.PIPE
            if input_value is not None:
                kwargs["stdin"] = subprocess.PIPE
            process = subprocess.Popen(command_list, **kwargs)
            export_log = _export_process_started(process, command_list, purpose, kwargs)
            child_pid = process.pid
            _note_child_start()
            _record_child_process(
                command_list,
                purpose,
                started=started,
                hidden=_hidden_launch(kwargs),
                returncode=None,
                child_pid=child_pid,
                phase="start",
                creationflags=int(kwargs.get("creationflags") or 0),
                original_command=original_command,
            )
            try:
                stdout, stderr = process.communicate(input_value, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                stop_process_tree(process)
                stdout, stderr = process.communicate()
                exc.stdout = stdout
                exc.stderr = stderr
                if export_log:
                    export_log.output('stdout', stdout); export_log.output('stderr', stderr)
                raise
            if export_log:
                export_log.output('stdout', stdout); export_log.output('stderr', stderr)
            completed = subprocess.CompletedProcess(command_list, process.returncode, stdout, stderr)
            if check:
                completed.check_returncode()
        from ..diagnostics.event_log import emit
        from ..diagnostics.event_bridge import stderr_evidence
        if getattr(completed,"returncode",0):
            emit("process.failure",level="ERROR",result="failed",purpose=purpose,child_pid=child_pid,
                 exit_code=completed.returncode,stderr_evidence=stderr_evidence(getattr(completed,"stderr",None)),
                 duration_ms=round((time.perf_counter()-started)*1000,3))
        return completed
    except BaseException as exc:
        from ..diagnostics.event_log import emit, exception_info
        from ..diagnostics.event_bridge import stderr_evidence
        emit("process.failure",level="ERROR",result="cancelled" if isinstance(exc,KeyboardInterrupt) else "failed",
             purpose=purpose,child_pid=child_pid,exit_code=getattr(completed,"returncode",getattr(exc,"returncode",None)),
             termination="timeout" if isinstance(exc,subprocess.TimeoutExpired) else "exception",
             exception=exception_info(exc),stderr_evidence=stderr_evidence(getattr(exc,"stderr",None)),
             duration_ms=round((time.perf_counter()-started)*1000,3))
        raise
    finally:
        if export_log:
            export_log.exited(process.returncode)
        _record_child_process(
            command_list,
            purpose,
            started=started,
            hidden=_hidden_launch(kwargs),
            returncode=getattr(completed, "returncode", None),
            child_pid=child_pid,
            phase="exit",
            creationflags=int(kwargs.get("creationflags") or 0),
            original_command=original_command,
        )


class _InstrumentedPopen:
    """Transparent Popen proxy that records duration at completion."""

    def __init__(
        self,
        process,
        command: list[object],
        purpose: str,
        started: float,
        hidden: bool,
        *,
        creationflags: int = 0,
        original_command: list[object] | None = None,
        redact_process_details: bool = False,
    ):
        self._process = process
        self._command = command
        self._original_command = original_command or command
        self._purpose = purpose
        self._started = started
        self._hidden = hidden
        self._creationflags = int(creationflags or 0)
        self._redact_process_details = bool(redact_process_details)
        self._recorded = False
        self._export_log = None
        from ..diagnostics.event_bridge import runtime_context_fields
        self._diagnostic_context=runtime_context_fields()

    def _record(self) -> None:
        if self._recorded:
            return
        code = self._process.poll()
        if code is None:
            return
        self._recorded = True
        if self._export_log:
            self._export_log.exited(code)
        _record_child_process(
            self._command,
            self._purpose,
            started=self._started,
            hidden=self._hidden,
            returncode=code,
            child_pid=getattr(self._process, "pid", None),
            phase="exit",
            creationflags=self._creationflags,
            original_command=self._original_command,
            redact_process_details=self._redact_process_details,
            diagnostic_context=self._diagnostic_context,
        )

    def poll(self):
        code = self._process.poll()
        if code is not None:
            self._record()
        return code

    def wait(self, *args, **kwargs):
        try:
            return self._process.wait(*args, **kwargs)
        finally:
            self._record()

    def communicate(self, *args, **kwargs):
        try:
            output = self._process.communicate(*args, **kwargs)
            if self._process.returncode:
                from ..diagnostics.event_log import emit
                from ..diagnostics.event_bridge import stderr_evidence
                emit("process.failure",level="ERROR",result="failed",child_pid=self._process.pid,
                     purpose=self._purpose,exit_code=self._process.returncode,stderr_evidence=stderr_evidence(output[1]),**self._diagnostic_context)
            if self._export_log:
                self._export_log.output('stdout', output[0])
                self._export_log.output('stderr', output[1])
            return output
        finally:
            self._record()

    def __enter__(self):
        self._process.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self._process.__exit__(exc_type, exc, traceback)
        finally:
            self._record()

    def __getattr__(self, name: str):
        return getattr(self._process, name)


def _export_process_started(process, command, purpose, kwargs):
    from ..exports.export_run_log import current_export_log
    logger = current_export_log()
    if logger is None:
        return None
    redirected = {channel: str(getattr(kwargs.get(channel), 'name'))
                  for channel in ('stdout', 'stderr')
                  if isinstance(getattr(kwargs.get(channel), 'name', None), (str, os.PathLike))}
    argv = [str(x) for x in command]
    text_mode = bool(kwargs.get('text') or kwargs.get('encoding') or kwargs.get('universal_newlines'))
    probe_text = (Path(argv[0]).stem.lower() == 'ffprobe' and any(
        option in argv for option in ('-show_packets', '-show_streams', '-show_format', '-show_entries')))
    try:
        return logger.process_started(command, purpose, process, cwd=kwargs.get('cwd'), redirected=redirected,
            capture_stdout=text_mode or probe_text, stderr_merged=kwargs.get('stderr') == subprocess.STDOUT)
    except BaseException:
        # The caller has not received the handle yet. A diagnostic write failure
        # must not strand a running export child outside cancellation ownership.
        try:
            stop_process_tree(process)
        except Exception:
            pass
        raise


def popen_hidden_subprocess(
    command: Iterable[object],
    *,
    purpose: str,
    process_factory: Callable[..., Any] | None = None,
    log_command: Iterable[object] | None = None,
    visible_console: bool = False,
    own_process_tree: bool = False,
    **kwargs,
):
    """Start a hidden child and instrument it when ``wait``/``poll`` completes.

    ``visible_console=True`` is the single sanctioned escape hatch for CLI
    login TUIs that cannot render through pipes: the child gets its own
    visible console instead of the hidden-window flags.  The caller owns the
    process and must terminate it via ``stop_process_tree`` when the flow
    completes.
    """
    original_command = list(command)
    recorded_command = list(log_command) if log_command is not None else list(original_command)
    command_list = canonical_subprocess_command(
        original_command,
        environ=kwargs.get("env"),
    )
    recorded_command_list = canonical_subprocess_command(
        recorded_command,
        environ=kwargs.get("env"),
    )
    if kwargs.get("env") is None:
        kwargs["env"] = sanitized_child_environment()
    if visible_console:
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # SW_SHOWNORMAL is a Win32 ShowWindow value, not a subprocess
            # constant. A new console needs visible startup flags even when
            # launched by the windowed frozen application.
            startupinfo.wShowWindow = 1
            flags = int(kwargs.get("creationflags", 0))
            flags &= ~(subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
            kwargs["creationflags"] = flags | subprocess.CREATE_NEW_CONSOLE
            kwargs.setdefault("startupinfo", startupinfo)
        kwargs.setdefault("cwd", str(Path.home()))
    else:
        options = hidden_subprocess_kwargs()
        for key, value in options.items():
            kwargs.setdefault(key, value)
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        kwargs.setdefault("stderr", subprocess.DEVNULL)
    from ..diagnostics.event_log import recorder
    from ..diagnostics.event_bridge import runtime_context_fields
    diagnostic = recorder()
    if diagnostic is not None:
        import json
        kwargs["env"] = dict(kwargs.get("env") or os.environ)
        kwargs["env"]["TWOBYTEASR_DIAGNOSTIC_PARENT"] = json.dumps({"parent_session_id":diagnostic.session_id,**runtime_context_fields()})
    started = time.perf_counter()
    if own_process_tree and os.name=='nt':
        kwargs['creationflags']=int(kwargs.get('creationflags',0))|0x4  # CREATE_SUSPENDED
    process = (process_factory or subprocess.Popen)(command_list, **kwargs)
    if own_process_tree and os.name=='nt':
        from .process_job import RequestProcessJob
        try:
            process._request_job=RequestProcessJob(process)
        except BaseException:
            process.kill();process.wait(timeout=3)
            raise
    _note_child_start()
    _record_child_process(
        recorded_command_list,
        purpose,
        started=started,
        hidden=(not visible_console and _hidden_launch(kwargs)),
        returncode=None,
        child_pid=getattr(process, "pid", None),
        phase="start",
        creationflags=int(kwargs.get("creationflags") or 0),
        original_command=recorded_command,
        redact_process_details=log_command is not None,
    )
    instrumented = _InstrumentedPopen(
        process,
        recorded_command_list,
        purpose,
        started,
        (not visible_console and _hidden_launch(kwargs)),
        creationflags=int(kwargs.get("creationflags") or 0),
        original_command=recorded_command,
        redact_process_details=log_command is not None,
    )
    instrumented._export_log = _export_process_started(process, command_list, purpose, kwargs)
    if instrumented._export_log:
        from ..exports.export_run_log import LoggedPipe
        for channel in ('stdout', 'stderr'):
            stream = getattr(process, channel, None)
            if stream is not None and (channel == 'stderr' or instrumented._export_log.capture_stdout):
                setattr(instrumented, channel, LoggedPipe(stream, instrumented._export_log, channel))
    return instrumented


def stop_process_tree(process, *, deadline_monotonic=None) -> None:
    """终止整个子进程树（含孙进程）并等待其真正退出；幂等。

    Windows 用 ``taskkill /T /F``（按进程树终止）；受限环境下 taskkill
    可能无法结束根进程时直接 kill 兜底。进程已退出时直接返回，不会
    产生新异常——取消与 watchdog 路径可以安全重复调用。
    """
    if process.poll() is not None:
        return
    remaining = lambda:max(0., min(3., deadline_monotonic-time.monotonic())) if deadline_monotonic is not None else 3.
    if os.name == "nt" and remaining() > 0:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=remaining(),
                **hidden_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired:
            pass
        # 受限环境下 taskkill 可能无法结束根进程；直接 kill 作为立即兜底。
        if process.poll() is None:
            process.kill()
    else:
        process.kill()
    try:
        process.wait(timeout=remaining())
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=remaining())
        except subprocess.TimeoutExpired:
            if deadline_monotonic is None:
                raise
            return False
    return True


def run_subprocess_with_tree_kill(command, *, timeout, **kwargs):
    """subprocess.run 的防挂死变体：超时杀整棵进程树 + 有界排空。

    Windows 上 ``Popen.communicate`` 在子进程已退出、但孙进程继承管道写端
    时会在 join reader 线程上永久阻塞（2026-09-03 run eaa7a3 实录：torch
    探测超时后的排空让队列线程卡死）。这里手动 pump + 有界 join，最坏情况
    丢弃输出并抛 TimeoutExpired，绝不无限等待。
    """
    kwargs.pop("capture_output", None)
    kwargs.pop("check", None)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    process = subprocess.Popen(command, **kwargs)
    chunks = {"stdout": [], "stderr": []}

    def _pump(stream, sink):
        try:
            sink.append(stream.read())
        except (OSError, ValueError):
            pass

    pumps = [
        threading.Thread(target=_pump, args=(process.stdout, chunks["stdout"]), daemon=True),
        threading.Thread(target=_pump, args=(process.stderr, chunks["stderr"]), daemon=True),
    ]
    for pump in pumps:
        pump.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_process_tree(process)
        try:
            returncode = process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            returncode = None
    # 有界 join：孙进程握住管道写端时放弃读取（daemon 线程随进程退出回收）。
    for pump in pumps:
        pump.join(timeout=5.0)
    stdout = chunks["stdout"][0] if chunks["stdout"] else ""
    stderr = chunks["stderr"][0] if chunks["stderr"] else ""
    if timed_out or returncode is None:
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


__all__ = [
    "canonical_subprocess_command",
    "child_process_start_count",
    "hidden_subprocess_kwargs",
    "main_python_executable",
    "popen_hidden_subprocess",
    "process_action_scope",
    "python_utf8_command",
    "run_hidden_subprocess",
    "run_subprocess_with_tree_kill",
    "stop_process_tree",
    "utf8_worker_environment",
]
