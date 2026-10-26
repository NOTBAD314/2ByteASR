"""Independent mpv process: Windows HWND/pipe, POSIX window/socket IPC."""

from __future__ import annotations

import ctypes
import json
import os
import select
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..system.processes import popen_hidden_subprocess, sanitized_child_environment
from ..diagnostics.playback_probe import mark as playback_mark
from .platform_mpv import (
    native_video_arguments, open_mpv_ipc, unix_ipc_path, cleanup_unix_ipc,
    preview_scale_filter, preview_scale_value,
)

# mpv bitmap slots compose in ascending order, above native ASS (ADR-0006).
VIDEO_OVERLAY_ID = 0
ADVANCED_OVERLAY_ID = 1
TRANSFORM_OVERLAY_ID = 2
VIDEO_TRANSFORM_OVERLAY_ID = 3


class MpvUnavailableError(RuntimeError):
    pass


class MpvIPCTimeoutError(RuntimeError):
    pass


class MpvCommandError(RuntimeError):
    """A valid mpv response rejecting a command, not an IPC transport fault."""

    def __init__(self, command: Iterable[Any], error: object) -> None:
        self.command = tuple(command)
        self.error = str(error)
        super().__init__(f"mpv command failed: {self.error}")


def find_mpv_executable(
    project_root: str | os.PathLike[str] | None = None,
    environ: dict[str, str] | None = None,
) -> Path | None:
    env = environ if environ is not None else os.environ
    candidates: list[Path] = []
    override = str(env.get("TWOBYTEASR_MPV") or "").strip()
    if override:
        candidates.append(Path(override))
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    binary_name = "mpv.exe" if os.name == "nt" else "mpv"
    candidates.append(root / "tools" / "mpv" / binary_name)
    local_app_data = str(env.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidates.append(
            Path(local_app_data)
            / "2ByteASR"
            / "SubtitleStudioPreview"
            / "tools"
            / binary_name
        )
    on_path = (shutil.which("mpv.exe") or shutil.which("mpv")) if os.name == "nt" else shutil.which("mpv")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def mpv_startup_arguments(
    executable: str | os.PathLike[str],
    window_id: int,
    ipc_path: str,
    *,
    log_path: str = "",
) -> list[str]:
    video_arguments = native_video_arguments(window_id)
    from ..runtime_paths import detect_install_root
    caption_fonts = detect_install_root() / 'assets' / 'fonts'
    arguments = [
        str(executable),
        "--no-config",
        "--idle=yes",
        "--keep-open=yes",
        "--force-window=yes",
        "--terminal=no",
        "--input-default-bindings=no",
        "--osc=no",
        "--osd-level=0",
        # Studio owns the editable subtitle track. Prevent mpv from loading
        # an adjacent/embedded SRT before the generated ASS is attached.
        "--sid=no",
        "--sub-auto=no",
        # Subtitle Studio owns the ASS style pipeline. mpv's default ASS
        # override can replace FontSize and make 52/500 appear nearly equal.
        "--sub-ass-override=no",
        # Qt font registration is process-local. Native libass must load the
        # same shipped faces as the authoring, measurement and export paths.
        f"--sub-fonts-dir={caption_fonts}",
        "--hwdec=auto-safe",
        "--vo=gpu-next",
        video_arguments[0],
        # Audio belongs to Studio's separate PCM sink. Display-sync may retime
        # video to a misreported monitor refresh rate without changing that
        # audio (even while mpv's speed property remains 1). With aid=no,
        # "audio" uses the system clock and preserves source timestamp cadence,
        # including VFR sections; captions follow those same video timestamps.
        "--video-sync=audio",
        "--audio-pitch-correction=yes",
        # All audible lanes share Studio's PCM mix; mpv never opens WASAPI.
        "--aid=no",
        *video_arguments[1:],
        f"--input-ipc-server={ipc_path}",
    ]
    # Explicit, process-local diagnostic comparisons; never persisted settings.
    hwdec = os.environ.get("TWOBYTEASR_DIAGNOSTIC_HWDEC", "")
    vo = os.environ.get("TWOBYTEASR_DIAGNOSTIC_VO", "")
    if hwdec in {"auto-safe", "no"}:
        arguments = [f"--hwdec={hwdec}" if v.startswith("--hwdec=") else v for v in arguments]
    if vo in {"gpu-next", "gpu"}:
        arguments = [f"--vo={vo}" if v.startswith("--vo=") else v for v in arguments]
    if log_path:
        arguments.extend(["--msg-level=all=warn", f"--log-file={log_path}"])
    return arguments


# The bundled Windows mpv.exe imports vulkan-1.dll, which only GPU drivers
# install. Without one, Windows refuses to start mpv (2026-10-17: VMs, remote
# desktops, basic display drivers). Studio renders through D3D11 and never
# creates a Vulkan instance, so a bundled Khronos loader only has to exist.
# Installs carry it in third_party/vulkan-loader (the 主程序 update component);
# a source tree gets it in tools/vulkan-loader from scripts/collect_tools.ps1.
VULKAN_LOADER_FOLDERS = (("third_party", "vulkan-loader"), ("tools", "vulkan-loader"))


def vulkan_loader_fallback_dir(root: str | os.PathLike[str] | None = None) -> Path | None:
    if root is None:
        from ..runtime_paths import detect_install_root
        root = detect_install_root()
    for parts in VULKAN_LOADER_FOLDERS:
        folder = Path(root).joinpath(*parts)
        if (folder / "vulkan-1.dll").is_file():
            return folder
    return None


def mpv_environment(
    environ: Mapping[str, str] | None = None,
    *,
    root: str | os.PathLike[str] | None = None,
    windows: bool | None = None,
) -> dict[str, str]:
    """mpv's child environment, with the bundled Vulkan loader LAST on PATH.

    Windows looks for a DLL in mpv.exe's folder, then System32, and only then
    along PATH. A GPU driver's own loader therefore always wins; the bundled
    one is used only on PCs that have none.
    """
    env = sanitized_child_environment(None if environ is None else dict(environ))
    if not (os.name == "nt" if windows is None else windows):
        return env
    folder = vulkan_loader_fallback_dir(root)
    if folder is None:
        return env
    entries = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    if os.path.normcase(str(folder)) not in {os.path.normcase(part) for part in entries}:
        entries.append(str(folder))
    env["PATH"] = os.pathsep.join(entries)
    return env


# NTSTATUS exit codes of a Windows child the loader could not start. mpv never
# ran any of its own code, so waiting or restarting it cannot help.
_STARTUP_FAILURES = {
    0xC0000135: "播放器缺少需要的运行库（通常是显卡驱动带的 vulkan-1.dll），无法启动（{code}）。请重新安装 2ByteASR，或安装显卡驱动。",
    0xC0000139: "播放器需要的系统文件版本不对（多半是旧的 vulkan-1.dll），无法启动（{code}）。请更新显卡驱动；仍不行请安装最新的 Vulkan Runtime。",
    0xC000007B: "播放器文件损坏或与这台电脑不兼容，无法启动（{code}）。请重新安装 2ByteASR。",
    0xC000012F: "播放器文件损坏或与这台电脑不兼容，无法启动（{code}）。请重新安装 2ByteASR。",
}


# A Windows child inherits its parent's hard-error mode. Studio started from
# Explorer or a shortcut has system error boxes on, so an mpv that Windows
# cannot load waited on a "找不到 vulkan-1.dll" box instead of exiting, and the
# readiness gate only saw a 30 s timeout (2026-10-17, Server 2019 VM).
_SEM_FAILCRITICALERRORS = 0x0001


def _kernel32():
    return ctypes.windll.kernel32 if os.name == "nt" else None


@contextmanager
def _without_system_error_boxes():
    """Start children with SEM_FAILCRITICALERRORS so a load failure just exits."""
    kernel32 = _kernel32()
    if kernel32 is None:
        yield
        return
    previous = kernel32.GetErrorMode()
    kernel32.SetErrorMode(previous | _SEM_FAILCRITICALERRORS)
    try:
        yield
    finally:
        kernel32.SetErrorMode(previous)


def startup_failure_message(returncode: object) -> str:
    """User-facing reason for an mpv that Windows could not load, else ''."""
    if not isinstance(returncode, int):
        return ""
    code = returncode & 0xFFFFFFFF
    source = _STARTUP_FAILURES.get(code)
    if source is None:
        return ""
    from ..i18n import tr
    return tr(source, code=f"0x{code:08X}")


def _ipc_pipe_name() -> str:
    if os.name != "nt":
        return unix_ipc_path()
    from ..system.windows_ipc import in_app_container
    namespace = 'LOCAL\\' if in_app_container() else ''
    return rf"\\.\pipe\{namespace}2byteasr-studio-{os.getpid()}-{uuid.uuid4().hex}"


class _MpvActorRequest:
    """One actor-owned IPC operation with optional latest-wins identity."""

    __slots__ = (
        "callback", "coalesce_key", "foreground", "deferred", "done",
        "result", "error", "on_discard",
        "submitted_at",
    )

    def __init__(
        self,
        callback: Callable[[], Any],
        *,
        coalesce_key: str = "",
        foreground: bool = False,
        deferred: bool = False,
        wait: bool = False,
        on_discard=None,
    ) -> None:
        self.callback = callback
        self.submitted_at = time.perf_counter()
        self.coalesce_key = str(coalesce_key)
        self.foreground = bool(foreground)
        self.deferred = bool(deferred)
        self.done = threading.Event() if wait else None
        self.result: Any = None
        self.error: BaseException | None = None
        self.on_discard = on_discard

    def discard(self):
        if self.on_discard is not None:
            callback,self.on_discard = self.on_discard,None
            try: callback()
            except Exception: pass


class _MpvCommandActor:
    """The only production owner of the persistent mpv IPC connection.

    GUI callers post mutation commands without waiting. Synchronous startup and
    diagnostics calls are serialized through the same queue. Property changes
    are observed on the persistent client connection; one lightweight heartbeat
    drains those events instead of the GUI polling six properties in sequence.
    """

    OBSERVED_PROPERTIES = (
        "video-out-params",
        "duration",
        "pause",
        "speed",
        "eof-reached",
        "idle-active",
        "seeking",
        "time-pos",
        "playback-time",
        "core-idle",
        "video-frame-info",
        "video-codec",
        "hwdec-current",
        "current-vo", "display-fps", "estimated-display-fps", "container-fps",
        "video-sync", "mpv-version", "video-params",
        "hwdec-interop",
        "audio-pts",
        "avsync",
        "audio-delay",
        "display-sync-active",
        "video-speed-correction",
        "estimated-frame-number",
        "sid",
        "sub-visibility",
        "track-list",
        "path",
        # [PlaybackPerf] 窗口增量来源。mpv v0.41 实测：decoder-frame-drop-count /
        # frame-drop-count / vo-delayed-frame-count / estimated-vf-fps 有效；
        # 旧代码的 drop-frame-count、vo-drop-frame-count 在该版本不存在（恒
        # property not found），mistimed-frame-count 依赖 vsync 上下文（拿不到记 N/A）。
        "decoder-frame-drop-count",
        "frame-drop-count",
        "vo-delayed-frame-count",
        "mistimed-frame-count",
        "estimated-vf-fps",
    )

    def __init__(self, controller: "MpvController") -> None:
        self.controller = controller
        self._condition = threading.Condition()
        self._requests: deque[_MpvActorRequest] = deque()
        self._stopping = False
        self._pipe = None
        self._read_buffer = b""
        self._ever_connected = False
        self._degraded = False
        self._reconnect_attempts = 0
        self._last_error = ""
        self._command_error_count = 0
        self._last_command_error = ""
        self._init_request_metrics()
        self._properties: dict[str, Any] = {}
        self._properties_lock = threading.Lock()
        self._property_sequence = 0
        # Monotonic timestamp of the last completed IPC exchange. A live pipe
        # completes the 75 ms heartbeat constantly; a wedged process leaves
        # this stale even though the OS still reports the process as running.
        self._last_exchange_ok_ts = time.monotonic()
        self._source_generation = self.controller.source_epoch
        self._seek_target: float | None = None
        self._seek_poll_until = 0.0
        self._position_observation: dict[str, Any] = {
            "source": "unobserved",
            "source_generation": 0,
            "actor_sequence": 0,
            "observed_monotonic_ts": time.monotonic(),
            "position": None,
        }
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="studio-mpv-actor",
        )
        self._thread.start()

    def is_actor_thread(self) -> bool:
        return threading.current_thread() is self._thread

    def _init_request_metrics(self):
        self._request_samples = deque(maxlen=512)
        self._submitted_count = self._coalesced_count = self._completed_count = 0
        self._queue_peak = 0

    def post(
        self,
        callback: Callable[[], Any],
        *,
        coalesce_key: str = "",
        foreground: bool = False,
        deferred: bool = False,
        on_discard=None,
    ) -> bool:
        request = _MpvActorRequest(
            callback,
            coalesce_key=coalesce_key,
            foreground=foreground,
            deferred=deferred,
            on_discard=on_discard,
        )
        with self._condition:
            if self._stopping:
                request.discard()
                return False
            if request.coalesce_key:
                for item in self._requests:
                    if item.done is None and item.coalesce_key == request.coalesce_key:
                        self._coalesced_count += 1
                        item.discard()
                self._requests = deque(
                    item
                    for item in self._requests
                    if item.done is not None or item.coalesce_key != request.coalesce_key
                )
            if request.foreground:
                insert_at = next(
                    (
                        index
                        for index, item in enumerate(self._requests)
                        if not item.foreground
                    ),
                    len(self._requests),
                )
                self._requests.insert(insert_at, request)
            elif request.deferred:
                self._requests.append(request)
            else:
                insert_at = next(
                    (
                        index
                        for index, item in enumerate(self._requests)
                        if item.deferred
                    ),
                    len(self._requests),
                )
                self._requests.insert(insert_at, request)
            self._submitted_count += 1
            self._queue_peak = max(self._queue_peak,len(self._requests))
            self._condition.notify()
        return True

    def call(self, callback: Callable[[], Any], timeout: float) -> Any:
        if self.is_actor_thread():
            return callback()
        request = _MpvActorRequest(callback, wait=True)
        with self._condition:
            if self._stopping:
                raise RuntimeError("mpv actor is stopping")
            self._requests.append(request)
            self._submitted_count += 1
            self._queue_peak = max(self._queue_peak,len(self._requests))
            self._condition.notify()
        if request.done is None or not request.done.wait(max(0.1, timeout) + 0.5):
            raise RuntimeError("mpv actor request timed out")
        if request.error is not None:
            raise request.error
        return request.result

    def property(self, name: str, default: Any = None) -> Any:
        with self._properties_lock:
            return self._properties.get(str(name), default)

    def properties(self) -> dict[str, Any]:
        with self._properties_lock:
            return dict(self._properties)

    def position_observation(self) -> dict[str, Any]:
        with self._properties_lock:
            return dict(self._position_observation)

    def status(self) -> dict[str, Any]:
        return {
            "degraded": self._degraded,
            "reconnect_attempts": self._reconnect_attempts,
            "last_error": self._last_error,
            "command_error_count": self._command_error_count,
            "last_command_error": self._last_command_error,
            "thread_alive": self._thread.is_alive(),
            "pipe_open": self._pipe is not None,
            "source_generation": self._source_generation,
            "actor_sequence": self._property_sequence,
            "seconds_since_exchange": round(time.monotonic() - self._last_exchange_ok_ts, 3),
        }

    def mark_exchange_ok(self) -> None:
        self._last_exchange_ok_ts = time.monotonic()

    def seconds_since_exchange(self) -> float:
        return time.monotonic() - self._last_exchange_ok_ts

    def mark_degraded(self, message: str) -> None:
        self._degraded = True
        self._last_error = str(message)

    def _remember_property(
        self,
        name: str,
        value: Any,
        *,
        source: str = "property_change",
    ) -> None:
        notification=None
        with self._properties_lock:
            self._property_sequence += 1
            self._properties[str(name)] = value
            if str(name) in {"time-pos", "playback-time"} and value is not None:
                changed=self._position_observation.get('position')!=value or self._position_observation.get('source_generation')!=self._source_generation
                playback_mark("mpv_time_pos", media_ms=float(value)*1000, generation=self._source_generation)
                self._position_observation = {
                    "source": str(source),
                    "source_generation": max(
                        self._source_generation, self.controller.source_epoch
                    ),
                    "actor_sequence": self._property_sequence,
                    "observed_monotonic_ts": time.monotonic(),
                    "observed_perf_counter_ts": time.perf_counter(),
                    "position": value,
                    "seek_target": self._seek_target,
                    "paused": bool(self._properties.get('pause', True)),
                    "playback_rate": float(self._properties.get('speed') or 1.),
                    "seeking": bool(self._properties.get('seeking', False)),
                }
                if changed:notification=dict(self._position_observation)
        observer=getattr(self.controller,'_position_observer',None)
        boundary=getattr(self.controller,'_caption_boundary_publisher',None)
        if notification is not None and boundary is not None:boundary.observe(notification)
        if notification is not None and callable(observer):
            try:observer(notification)
            except RuntimeError:pass  # A closed Qt recipient cannot revive playback.

    def begin_seek(self, generation: int, target: float) -> None:
        """Advance the controller-owned epoch before the matching command."""
        self.controller._advance_source_epoch(int(generation))
        self._source_generation = self.controller.source_epoch
        self._seek_target = max(0.0, float(target))
        self._seek_poll_until = time.monotonic()+.35

    def _handle_event(self, payload: dict[str, Any]) -> None:
        name=payload.get('event')
        if name in {'start-file','file-loaded','end-file','shutdown','playback-restart'} or (name=='property-change' and payload.get('name') in {'pause','idle-active','speed','mute'}):
            from ..diagnostics.event_log import emit
            emit('player.state',module='mpv',phase=name,property=payload.get('name'),value=payload.get('data') if name=='property-change' else None,
                 reason=payload.get('reason'),result='failed' if payload.get('error') else 'observed',source_epoch=self.controller.source_epoch)
        if payload.get('event') == 'file-loaded':
            self.controller._subtitle_file_loaded()
        if payload.get("event") == "property-change" and payload.get("name"):
            self._remember_property(
                str(payload["name"]), payload.get("data"), source="property_change"
            )

    def _open_pipe(self, timeout: float) -> None:
        if self._pipe is not None:
            return
        deadline = time.monotonic() + max(0.1, timeout)
        last_error: OSError | None = None
        while time.monotonic() < deadline and not self._stopping:
            try:
                self._pipe = open_mpv_ipc(self.controller._pipe_path, timeout=max(0.01, deadline - time.monotonic()))
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.025)
        if self._pipe is None:
            raise RuntimeError(f"mpv IPC pipe did not become ready: {last_error}")
        try:
            for observer_id, name in enumerate(self.OBSERVED_PROPERTIES, start=1):
                self._exchange_on_pipe(
                    ["observe_property", observer_id, name], timeout=timeout,
                )
            if self._ever_connected:
                self.controller._restore_desired_state(self)
            self._ever_connected = True
            self._degraded = False
            self._last_error = ""
        except BaseException:
            self._drop_pipe()
            raise

    def _drop_pipe(self) -> None:
        pipe = self._pipe
        self._pipe = None
        self._read_buffer = b""
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass

    def _readline_with_timeout(self, timeout: float) -> bytes:
        pipe = self._pipe
        if pipe is None:
            raise RuntimeError("mpv IPC pipe is not open")
        deadline = time.monotonic() + max(0.01, timeout)
        while not self._stopping:
            if b"\n" in self._read_buffer:
                line, self._read_buffer = self._read_buffer.split(b"\n", 1)
                return line + b"\n"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MpvIPCTimeoutError(f"mpv IPC response timed out after {timeout:.3f}s")
            try:
                descriptor = pipe.fileno()
            except (AttributeError, OSError):
                # Test doubles and legacy non-Windows streams are already
                # in-memory/nonblocking; keep their direct readline contract.
                return pipe.readline()
            if os.name == "nt":
                import msvcrt

                available = ctypes.c_ulong(0)
                handle = msvcrt.get_osfhandle(descriptor)
                ok = ctypes.windll.kernel32.PeekNamedPipe(
                    ctypes.c_void_p(handle), None, 0, None,
                    ctypes.byref(available), None,
                )
                if not ok:
                    raise OSError(ctypes.get_last_error(), "PeekNamedPipe failed")
                if available.value:
                    chunk = os.read(descriptor, int(available.value))
                    if not chunk:
                        raise BrokenPipeError("mpv IPC pipe closed")
                    self._read_buffer += chunk
                    continue
            else:
                ready, _write, _error = select.select([descriptor], [], [], min(0.025, remaining))
                if ready:
                    chunk = os.read(descriptor, 65536)
                    if not chunk:
                        raise BrokenPipeError("mpv IPC pipe closed")
                    self._read_buffer += chunk
                    continue
            # Poll only while one IPC response is in flight. A 5 ms quantum is
            # visible twice in the Native-off -> Advanced-overlay ownership
            # handoff; 1 ms keeps that acknowledged swap within the live gate
            # without adding any idle polling.
            time.sleep(min(0.001, remaining))
        raise RuntimeError("mpv actor is stopping")

    def _exchange_on_pipe(
        self,
        command: Iterable[Any],
        *,
        timeout: float = 2.0,
    ) -> dict[str, Any]:
        pipe = self._pipe
        if pipe is None:
            raise RuntimeError("mpv IPC pipe is not open")
        self.controller._request_id += 1
        request_id = self.controller._request_id
        payload = {"command": list(command), "request_id": request_id}
        pipe.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        # Named-pipe reads are blocking, but mpv always returns one response for
        # every command. The actor owns that wait; the GUI never does for posts.
        while True:
            response = self._readline_with_timeout(timeout)
            parsed = json.loads(response.decode("utf-8")) if response else {}
            if parsed.get("request_id") == request_id:
                if parsed.get("error") not in {None, "success"}:
                    error = MpvCommandError(command, parsed.get("error"))
                    self._command_error_count += 1
                    self._last_command_error = str(error)
                    raise error
                return parsed
            self._handle_event(parsed)

    def exchange(
        self,
        command: Iterable[Any],
        *,
        timeout: float = 2.0,
    ) -> dict[str, Any]:
        if not self.is_actor_thread():
            raise RuntimeError("mpv IPC exchange attempted outside actor")
        values = list(command)
        for attempt in range(2):
            try:
                self._open_pipe(timeout)
                response = self._exchange_on_pipe(values, timeout=timeout)
                if values[:1] == ["get_property"] and len(values) > 1:
                    self._remember_property(
                        str(values[1]), response.get("data"), source="heartbeat"
                    )
                self._degraded = False
                self._last_error = ""
                self._last_exchange_ok_ts = time.monotonic()
                return response
            except MpvCommandError:
                # The pipe delivered a complete response. Reconnecting cannot
                # make a command valid (for example, seeking while mpv is
                # idle at EOF) and would starve later actor requests.
                raise
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                self._degraded = True
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._drop_pipe()
                if attempt or self._stopping or not self.controller.running:
                    raise
                self._reconnect_attempts += 1
                time.sleep(0.05)
        raise RuntimeError("mpv IPC retry exhausted")

    def _heartbeat(self) -> None:
        if not self.controller.running:
            self.mark_degraded("mpv process exited")
            self._drop_pipe()
            return
        try:
            # This response also drains every queued property-change event from
            # the persistent observed client connection.
            self.controller._send(["get_property", "time-pos"], timeout=0.5)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            pass

    def _drain_property_events(self) -> None:
        """Read already available events without a request or a blocking read.

        Previously an idle command queue held frame observations in the pipe
        until the next 75 ms heartbeat, dating old events as if they were new.
        """
        if self._pipe is None:return
        try:
            descriptor=self._pipe.fileno()
            if os.name=='nt':
                import msvcrt
                available=ctypes.c_ulong()
                if not ctypes.windll.kernel32.PeekNamedPipe(ctypes.c_void_p(msvcrt.get_osfhandle(descriptor)),
                    None,0,None,ctypes.byref(available),None):return
                if available.value:self._read_buffer+=os.read(descriptor,int(available.value))
            elif select.select([descriptor],[],[],0)[0]:
                self._read_buffer+=os.read(descriptor,65536)
            while b'\n' in self._read_buffer:
                line,self._read_buffer=self._read_buffer.split(b'\n',1)
                if line:self._handle_event(json.loads(line.decode('utf8')))
        except (OSError,ValueError,AttributeError):
            return  # The existing heartbeat performs transport recovery.

    def _run(self) -> None:
        # Python 3.10's Windows sleep(1ms) otherwise measured ~15.2ms.
        # Scope the matching request/release to the live IPC actor; this also
        # avoids a full timer quantum on every PNG -> mpv acknowledgement.
        timer_period = False
        if os.name == 'nt':
            timer_period = ctypes.windll.winmm.timeBeginPeriod(1) == 0
        try:
            self._run_loop()
        finally:
            if timer_period:
                ctypes.windll.winmm.timeEndPeriod(1)

    def _run_loop(self) -> None:
        next_heartbeat = time.monotonic()
        while True:
            request = None
            with self._condition:
                timeout = max(0.0, next_heartbeat - time.monotonic())
                if not self._requests and not self._stopping:
                    event_interval=.004 if self._pipe is not None and not self.property('pause',True) else .075
                    self._condition.wait(min(event_interval, timeout) if timeout else 0.0)
                if self._requests:
                    request = self._requests.popleft()
                elif self._stopping:
                    break
            if request is not None:
                request_started = time.perf_counter()
                try:
                    # A newer media event may already be waiting in the pipe.
                    # Consume it before an old GUI raster's valid_when guard.
                    self._drain_property_events()
                    request.result = request.callback()
                except BaseException as exc:
                    request.error = exc
                finally:
                    ended = time.perf_counter()
                    with self._condition:
                        self._completed_count += 1
                        self._request_samples.append((1000*(request_started-request.submitted_at),
                            1000*(ended-request_started),request.error is not None))
                    if request.done is not None:
                        request.done.set()
            now = time.monotonic()
            self._drain_property_events()
            # A frame event can enqueue a prepared caption while draining.
            # Publish that foreground work before an otherwise due heartbeat
            # starts another blocking IPC exchange in front of it.
            with self._condition:
                foreground_pending=bool(self._requests and self._requests[0].foreground)
            if foreground_pending:continue
            interval=.008 if now<self._seek_poll_until else .075
            if (now >= next_heartbeat or next_heartbeat-now>interval) and not self._stopping:
                self._heartbeat()
                next_heartbeat = now + interval
        self._drop_pipe()

    def request_metrics(self):
        from ..diagnostics.playback_metrics import distribution
        with self._condition:
            samples=list(self._request_samples)
            counters=dict(submitted=self._submitted_count,completed=self._completed_count,
                coalesced=self._coalesced_count,queue_depth=len(self._requests),queue_peak=self._queue_peak,
                retained_samples=len(samples),sample_capacity=self._request_samples.maxlen)
        return {**counters,'clock':'perf_counter / QPC',
            'queue_ms':distribution([r[0] for r in samples]),
            'execute_ack_ms':distribution([r[1] for r in samples]),
            'sample_errors':sum(r[2] for r in samples)}

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            pending = tuple(self._requests)
            self._requests.clear()
            self._condition.notify_all()
        self._drop_pipe()
        for request in pending:
            request.error = RuntimeError("mpv actor stopped")
            request.discard()
            if request.done is not None:
                request.done.set()
        if self._thread.is_alive() and not self.is_actor_thread():
            self._thread.join(timeout=1.0)


class MpvController:
    """Own one mpv child process and serialize commands through its named pipe."""

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        *,
        project_root: str | os.PathLike[str] | None = None,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        resolved = Path(executable).resolve() if executable else find_mpv_executable(project_root)
        if resolved is None or not resolved.is_file():
            raise MpvUnavailableError(
                "Subtitle Studio 需要 mpv 预览运行时。请重新运行安装器修复，"
                "或通过 TWOBYTEASR_MPV 指向可信的 mpv.exe。"
            )
        self.executable = resolved
        self._process_factory = process_factory
        self._process: subprocess.Popen | None = None
        self._pipe_path = ""
        self._request_id = 0
        self._actor: _MpvCommandActor | None = None
        self._studio_subtitle_sid: int | str | None = None
        self._studio_subtitle_path = ""
        self._subtitle_binding_epoch = 0
        self._subtitle_media_path = ''
        self._subtitle_media_ready = False
        self._desired_subtitle_path = ''
        self._subtitle_visible = True
        self._desired_commands: dict[str, list[Any]] = {}
        # Seek-observation epoch owned by the controller; it survives actor
        # and pipe restarts. Replacement PlaybackClocks sync to it so seek
        # acknowledgements stay comparable across projects.
        self._source_epoch = 0
        self._visual_apply_lock = threading.Lock()
        self._visual_apply_sequence = 0
        self._visual_applied: dict[str, Any] = {
            "subtitle": {"visible": None, "sequence": 0},
            "overlays": {},
        }
        self._seek_apply_lock = threading.Lock()
        self._seek_applied: dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def exit_code(self) -> int | None:
        """The child's exit status once it has exited; None before that."""
        process = self._process
        return None if process is None else process.poll()

    def source_alive(self, *, max_silence_s: float = 5.0) -> bool:
        """True while the child lives AND the IPC pipe still answers.

        A wedged process (lost D3D device, blocked core) keeps ``running``
        True while every exchange times out. The actor heartbeat exchanges
        every 75 ms, so a healthy pipe never approaches the silence budget.
        """
        if not self.running or self._actor is None:
            return False
        return self._actor.seconds_since_exchange() <= max_silence_s

    @property
    def source_epoch(self) -> int:
        return self._source_epoch

    def _advance_source_epoch(self, generation: int) -> None:
        self._source_epoch = max(self._source_epoch, int(generation))

    def start(self, window_id: int, *, log_path: str = "") -> None:
        if self.running:
            return
        self._pipe_path = _ipc_pipe_name()
        try:
            with _without_system_error_boxes():
                self._process = popen_hidden_subprocess(
                    mpv_startup_arguments(
                        self.executable, window_id, self._pipe_path, log_path=log_path
                    ),
                    purpose="mpv studio preview",
                    process_factory=self._process_factory,
                    env=mpv_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except BaseException:
            if os.name != "nt":
                cleanup_unix_ipc(self._pipe_path)
            raise
        self._actor = _MpvCommandActor(self)

    def _send(self, command: Iterable[Any], timeout: float = 2.0) -> dict[str, Any]:
        if not self.running:
            if self._actor is not None:
                self._actor.mark_degraded("mpv process exited")
            raise RuntimeError("mpv is not running")
        values = list(command)
        from ..diagnostics.event_log import emit
        if values and (values[0] in {"loadfile","seek","stop","frame-step","frame-back-step"} or
                       values[0] in {"set","set_property"} and len(values)>1 and values[1] in {"pause","speed","mute"}):
            import inspect
            emit("player.command", result="started", source=inspect.currentframe().f_back.f_code.co_name,
                 command_id=values[0], property_id=values[1] if values[0] in {"set","set_property"} else None,
                 value=values[2] if values[0] in {"set","set_property"} and len(values)>2 else None,
                 source_seconds=values[1] if values[0]=="seek" else None,
                 media_path=values[1] if values[0]=="loadfile" else None,
                 player_pid=getattr(self._process,"pid",None), source_epoch=getattr(self,"_source_epoch",None))
        actor = self._actor
        if actor is None:
            # start() always creates the actor; only a half-constructed
            # controller (tests) can get here.
            raise RuntimeError("mpv actor is not running")
        started = time.perf_counter()
        try:
            return actor.call(lambda: actor.exchange(values, timeout=timeout), timeout)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            if elapsed >= 20:
                from ..diagnostics.editor_diagnostics import record
                record("MPV_COMMAND", command=str(values[0]), duration_ms=round(elapsed, 3),
                       gui_thread=threading.current_thread() is threading.main_thread())

    def _post(
        self,
        callback: Callable[[], Any],
        *,
        coalesce_key: str,
        foreground: bool = False,
        deferred: bool = False,
        on_discard=None,
    ) -> bool:
        from ..diagnostics.event_log import context, current_context
        submitted_context = current_context()
        original_callback = callback
        def callback():
            with context(**submitted_context):
                return original_callback()
        actor = self._actor
        if actor is None:
            if on_discard is not None: on_discard()
            return False
        if not self.running:
            actor.mark_degraded("mpv process exited")
            if on_discard is not None: on_discard()
            return False
        return actor.post(
            callback,
            coalesce_key=coalesce_key,
            foreground=foreground,
            deferred=deferred,
            on_discard=on_discard,
        )

    def observed_property(self, name: str, default: Any = None) -> Any:
        actor = self._actor
        return actor.property(name, default) if actor is not None else default

    def observed_properties(self) -> dict[str, Any]:
        actor = self._actor
        return actor.properties() if actor is not None else {}

    def observed_position(self) -> dict[str, Any]:
        actor = self._actor
        return actor.position_observation() if actor is not None else {
            "source": "unobserved",
            "source_generation": 0,
            "actor_sequence": 0,
            "observed_monotonic_ts": time.monotonic(),
            "position": None,
        }

    def _record_visual_applied(self, target: str | int, visible: bool) -> None:
        """Record compositor state only after mpv acknowledges the mutation."""
        with self._visual_apply_lock:
            self._visual_apply_sequence += 1
            acknowledged_at = time.perf_counter()
            state = {
                "visible": bool(visible),
                "sequence": self._visual_apply_sequence,
                "monotonic": acknowledged_at,
                "perf_counter": acknowledged_at,
            }
            if target == "subtitle":
                self._visual_applied["subtitle"] = state
            else:
                self._visual_applied["overlays"][int(target)] = state

    def applied_visual_state(self) -> dict[str, Any]:
        """Return acknowledged subtitle/overlay state for ownership evidence."""
        with self._visual_apply_lock:
            return {
                "sequence": self._visual_apply_sequence,
                "subtitle": dict(self._visual_applied["subtitle"]),
                "overlays": {
                    int(overlay_id): dict(state)
                    for overlay_id, state in self._visual_applied["overlays"].items()
                },
            }

    def applied_seek_state(self) -> dict[str, Any]:
        with self._seek_apply_lock:
            return dict(self._seek_applied)

    def actor_status(self) -> dict[str, Any]:
        actor = self._actor
        return actor.status() if actor is not None else {
            "degraded": not self.running,
            "reconnect_attempts": 0,
            "last_error": "mpv actor unavailable",
            "thread_alive": False,
            "pipe_open": False,
        }

    def _remember_desired(self, key: str, command: Iterable[Any]) -> None:
        self._desired_commands[str(key)] = list(command)

    # Only transport-neutral state is safe to replay after an IPC reconnect:
    # the mpv process kept its media and position, so replaying a remembered
    # seek/loadfile would yank playback back to a stale target (one source of
    # the packaged-EXE backward-seek loop). Seek, subtitle-file, and overlay
    # commands are therefore never stored here — only the keys below are
    # replayed by _restore_desired_state.
    _REPLAYABLE_DESIRED_KEYS = frozenset({
        "pause", "speed", "volume", "audio-output", "subtitle-visibility",
        "preview-scale",
    })

    def _restore_desired_state(self, actor: _MpvCommandActor) -> None:
        for key, command in tuple(self._desired_commands.items()):
            if str(key) not in self._REPLAYABLE_DESIRED_KEYS:
                continue
            try:
                actor._exchange_on_pipe(command, timeout=0.75)
            except MpvCommandError:
                # Desired state can contain media-dependent commands. At EOF
                # they may be temporarily invalid, but they must not abort
                # reconnection or block speed/pause state.
                continue

    def post_seek(
        self,
        seconds: float,
        *,
        accurate: bool = True,
        generation: int = 0,
    ) -> bool:
        mode = "absolute+exact" if accurate else "absolute+keyframes"
        target = max(0.0, float(seconds))
        command = ["seek", target, mode]

        def perform_seek() -> dict[str, Any]:
            actor = self._actor
            if actor is not None:
                actor.begin_seek(generation, target)
            # 2026-09-02 修复（EOF 二段）：EOF 后 mpv 停机（eof-reached），直接 seek 有时
            # 不出新帧（画面停在最后帧/黑屏）。先暂停再 seek，并强制步进一帧。
            # 注意 ``set`` 命令只接受字符串值（JSON 布尔会被 mpv 拒收并抛
            # MpvCommandError，把后面的 seek 一起吞掉）——恢复分支必须用
            # ``set_property`` 且不得让辅助命令的失败中断主 seek。
            eof = False
            try:
                eof = bool(actor.properties().get("eof-reached")) if actor is not None else False
            except Exception:
                eof = False
            if eof:
                try:
                    self._send(["set_property", "pause", True])
                except Exception:
                    pass
            result = self._send(command)
            if eof:
                try:
                    self._send(["frame-step"])
                except Exception:
                    pass
            with self._seek_apply_lock:
                self._seek_applied = {
                    "generation": int(generation),
                    "target": target,
                    "perf_counter": time.perf_counter(),
                }
            return result

        return self._post(
            perform_seek,
            coalesce_key="seek",
        )

    def post_load(self, media_path: str | os.PathLike[str]) -> bool:
        target = str(Path(media_path).resolve())
        self._begin_subtitle_media(target)
        epoch = self._subtitle_binding_epoch
        return self._post(
            lambda: self._send(['loadfile', target, 'replace']) if epoch == self._subtitle_binding_epoch else None,
            coalesce_key="loadfile",
            foreground=True,
        )

    def post_load_at(
        self,
        media_path: str | os.PathLike[str],
        seconds: float,
        *,
        generation: int,
    ) -> bool:
        """Load a new source at its mapped time in one mpv command.

        A separate ``loadfile`` followed by ``seek`` races mpv's asynchronous
        file initialization. The seek can be rejected before ``file-loaded``
        and leave PlaybackClock waiting forever for an acknowledgement.
        """

        source = str(Path(media_path).resolve())
        self._begin_subtitle_media(source)
        epoch = self._subtitle_binding_epoch
        target = max(0.0, float(seconds))
        command = [
            "loadfile",
            source,
            "replace",
            -1,
            {"start": f"{target:.6f}"},
        ]

        def perform_load_at() -> dict[str, Any]:
            if epoch != self._subtitle_binding_epoch:
                return {}
            actor = self._actor
            if actor is not None:
                actor.begin_seek(generation, target)
            result = self._send(command)
            with self._seek_apply_lock:
                self._seek_applied = {
                    "generation": int(generation),
                    "target": target,
                    "perf_counter": time.perf_counter(),
                    "command": "loadfile-start",
                }
            return result

        return self._post(
            perform_load_at,
            coalesce_key="loadfile",
            foreground=True,
        )

    def post_clear_media(self) -> bool:
        self._begin_subtitle_media('')
        self._desired_subtitle_path = ''
        epoch = self._subtitle_binding_epoch
        return self._post(
            lambda: self._send(['stop']) if epoch == self._subtitle_binding_epoch else None,
            coalesce_key="loadfile",
            foreground=True,
        )

    def post_set_paused(self, paused: bool, *, position_seconds: float | None = None) -> bool:
        value = bool(paused)
        command = ["set_property", "pause", value]

        def perform() -> dict[str, Any]:
            # 2026-09-02 修复：EOF 停机态下解除暂停不会重启解码（黑屏无声）。
            # 播放请求时若已 eof：先回到当前显示位置（或片头）再播放。
            # 恢复命令用 set_property（set 只收字符串值，布尔会抛
            # MpvCommandError 并连带吞掉真正的主命令）。
            if not value:
                actor = self._actor
                eof = False
                try:
                    eof = bool(actor.properties().get("eof-reached")) if actor is not None else False
                except Exception:
                    eof = False
                if eof:
                    try:
                        position = float(
                            (actor.properties().get("time-pos") or 0.0)
                        )
                    except Exception:
                        position = 0.0
                    try:
                        self._send(["set_property", "pause", True])
                        self._send(["seek", max(0.0, position - 0.05), "absolute+exact"])
                    except Exception:
                        pass
            result = self._send(command)
            if value and position_seconds is not None:
                self._send(["seek", max(0., position_seconds), "absolute+exact"])
            playback_mark("mpv_pause_applied",paused=value,source_epoch=self._source_epoch)
            return result

        self._remember_desired("pause", command)
        return self._post(
            perform,
            coalesce_key="pause",
        )

    def post_set_speed(self, value: float) -> bool:
        actual = min(8.0, max(0.1, float(value)))
        command = ["set_property", "speed", actual]
        self._remember_desired("speed", command)
        return self._post(
            lambda: self._send(command),
            coalesce_key="speed",
        )

    def post_set_preview_scale(self, scale: float) -> bool:
        """Shrink decoded frames for a lighter preview (1, 0.5 or 0.25).

        The `vf` option survives loadfile; the filter suits the decoder mpv
        last reported, and Studio posts again when that decoder changes.
        """
        hwdec = str(self.observed_property("hwdec-current", "") or "")
        command = ["set_property", "vf", preview_scale_filter(preview_scale_value(scale), hwdec=hwdec)]
        self._remember_desired("preview-scale", command)
        return self._post(
            lambda: self._send(command),
            coalesce_key="preview-scale",
        )

    def post_set_volume(self, value: float) -> bool:
        actual = min(100.0, max(0.0, float(value)))
        command = ["set_property", "volume", actual]
        self._remember_desired("volume", command)
        return self._post(
            lambda: self._send(command),
            coalesce_key="volume",
        )

    def post_set_audio_enabled(self, enabled: bool) -> bool:
        """Enable or fully disable mpv audio decoding/output asynchronously."""

        value = "auto" if bool(enabled) else "no"
        command = ["set_property", "aid", value]
        self._remember_desired("audio-output", command)
        return self._post(
            lambda: self._send(command),
            coalesce_key="audio-output",
        )

    def post_subtitle_file(self, ass_path: str | os.PathLike[str]) -> bool:
        path = str(Path(ass_path).resolve())
        # Store this session's intent before a same-project proxy rebind can
        # advance the media epoch. Only clear_media clears subtitle ownership.
        self._desired_subtitle_path = path
        epoch = self._subtitle_binding_epoch
        return self._post(
            lambda: self.set_subtitle_file(path) if epoch == self._subtitle_binding_epoch else None,
            coalesce_key="subtitle-file",
        )

    def post_set_subtitle_visible(self, visible: bool) -> bool:
        value = bool(visible)
        # Store intent synchronously: a reconnect between post and execution
        # must still replay the latest visibility, not the previous one.
        command = ["set_property", "sub-visibility", value]
        self._subtitle_visible = value
        self._remember_desired("subtitle-visibility", command)
        return self._post(
            lambda: self.set_subtitle_visible(value),
            coalesce_key="subtitle-visibility",
            foreground=True,
        )

    def post_raw_overlay(
        self,
        overlay_id: int,
        path: str | os.PathLike[str],
        valid_when=None,
        on_applied=None,
        on_started=None,
        coalesce_key=None,
        **geometry: Any,
    ) -> bool:
        overlay = int(overlay_id)
        target = os.path.abspath(path)
        command: list[Any] = [
            "overlay-add", overlay, int(geometry["x"]), int(geometry["y"]),
            target, 0, str(geometry.get("pixel_format", "bgra")),
            max(1, int(geometry["width"])), max(1, int(geometry["height"])),
            max(4, int(geometry["stride"])),
        ]
        if geometry.get("display_width") is not None or geometry.get("display_height") is not None:
            command.extend([
                max(1, int(geometry.get("display_width") or geometry["width"])),
                max(1, int(geometry.get("display_height") or geometry["height"])),
            ])
        def publish():
            applied=False
            try:
                if valid_when is not None and not valid_when():return
                boundary=getattr(self,'_caption_boundary_publisher',None)
                cue_id=geometry.get('cue_id')
                if boundary is not None and cue_id and not boundary.allows(cue_id):return
                if on_started is not None:on_started()
                self._send(command)
                self._record_visual_applied(overlay, True)
                applied=True
            finally:
                if on_applied is not None:on_applied(applied)
        return self._post(
            publish,
            coalesce_key=coalesce_key or f"overlay:{overlay}",
            foreground=overlay == ADVANCED_OVERLAY_ID,
            deferred=overlay != ADVANCED_OVERLAY_ID,
            on_discard=(lambda:on_applied(False)) if on_applied is not None else None,
        )

    def post_remove_overlay(self, overlay_id: int, *, cue_id=None) -> bool:
        overlay = int(overlay_id)
        def remove_current():
            boundary=getattr(self,'_caption_boundary_publisher',None)
            if boundary is not None and cue_id and not boundary.allows(cue_id):return
            self.remove_overlay(overlay)
        return self._post(
            remove_current,
            coalesce_key=f"overlay:{overlay}",
            foreground=overlay == ADVANCED_OVERLAY_ID,
            deferred=overlay != ADVANCED_OVERLAY_ID,
        )

    def load(self, media_path: str | os.PathLike[str]) -> None:
        self._begin_subtitle_media(str(Path(media_path).resolve()))
        self._send(["loadfile", str(Path(media_path).resolve()), "replace"])

    def _begin_subtitle_media(self, source):
        self._subtitle_binding_epoch += 1
        self._subtitle_media_path = source
        self._subtitle_media_ready = False
        self._studio_subtitle_sid = None
        self._studio_subtitle_path = ""

    def _subtitle_file_loaded(self):
        # Events are read during IPC exchanges. Queue work instead of nesting
        # another synchronous exchange inside the pipe reader.
        epoch = self._subtitle_binding_epoch
        source = self._subtitle_media_path
        def bind():
            if epoch != self._subtitle_binding_epoch or not source:
                return
            actual = str(self.get_property('path', '') or '')
            if not actual or Path(actual).resolve() != Path(source).resolve():
                return
            self._subtitle_media_ready = True
            if self._desired_subtitle_path:
                self.set_subtitle_file(self._desired_subtitle_path)
        self._post(bind, coalesce_key='subtitle-media-ready')

    def set_subtitle_file(self, ass_path: str | os.PathLike[str]) -> None:
        path = str(Path(ass_path).resolve())
        self._desired_subtitle_path = path
        if not self._subtitle_media_ready:
            return
        epoch = self._subtitle_binding_epoch
        # mpv can discover sidecar subtitle files after loadfile even when an
        # earlier build omitted --sub-auto=no. Remove every external subtitle
        # track before attaching Studio's generated ASS; embedded tracks may
        # remain available, but are never selected in editable preview mode.
        try:
            tracks = self.get_property("track-list", [])
        except RuntimeError:
            tracks = []
        if epoch != self._subtitle_binding_epoch:
            return
        if isinstance(tracks, list):
            for track in tracks:
                if not isinstance(track, dict) or track.get("type") != "sub":
                    continue
                track_id = track.get("id")
                external = bool(
                    track.get("external")
                    or track.get("external-filename")
                )
                if external and track_id not in {None, False, "no"}:
                    self._send(["sub-remove", track_id])
        # Cached sid belongs to a previous load. A valid empty track-list is
        # authoritative; removing that unloaded id would abort the new sub-add.
        if epoch != self._subtitle_binding_epoch:
            return
        self._send(["sub-add", path, "select"])
        try:
            sid = self.get_property("sid")
        except RuntimeError:
            sid = None
        if epoch != self._subtitle_binding_epoch:
            return
        self._studio_subtitle_sid = sid if sid not in {False, "no"} else None
        self._studio_subtitle_path = path

    def set_subtitle_visible(self, visible: bool) -> None:
        value = bool(visible)
        self._subtitle_visible = value
        self._remember_desired(
            "subtitle-visibility", ["set_property", "sub-visibility", value]
        )
        self._send(["set_property", "sub-visibility", value])
        self._record_visual_applied("subtitle", value)

    def clear_media(self) -> None:
        """Enter mpv idle state without terminating or replacing the child."""
        # mpv's ``stop`` command stops playback *and clears the playlist*.
        # With --idle=yes the same process remains ready for Undo/restoration.
        # Extra pause/playlist-clear round trips made last-segment Delete wait
        # for three named-pipe responses with no additional state guarantee.
        self._subtitle_binding_epoch += 1
        self._subtitle_media_path = ''
        self._subtitle_media_ready = False
        self._desired_subtitle_path = ''
        self._send(["stop"])
        self._studio_subtitle_sid = None
        self._studio_subtitle_path = ""

    def subtitle_diagnostics(self) -> dict[str, Any]:
        """Return debug state for the single Studio-owned subtitle track."""
        result: dict[str, Any] = {
            "studio_subtitle_sid": self._studio_subtitle_sid,
            "studio_subtitle_path": self._studio_subtitle_path,
            "subtitle_visible": self._subtitle_visible,
        }
        for name in ("sid", "track-list"):
            try:
                result[name] = self.get_property(name)
            except RuntimeError as exc:
                result[name] = f"unavailable: {exc}"
        return result

    def set_paused(self, paused: bool) -> None:
        self._send(["set_property", "pause", bool(paused)])

    def seek(self, seconds: float, *, accurate: bool = True) -> None:
        mode = "absolute+exact" if accurate else "absolute+keyframes"
        self._send(["seek", max(0.0, float(seconds)), mode])

    def frame_step(self, backwards: bool = False) -> None:
        self._send(["frame-back-step" if backwards else "frame-step"])

    def set_volume(self, value: float) -> None:
        self._send(["set_property", "volume", min(100.0, max(0.0, float(value)))])

    def set_audio_enabled(self, enabled: bool) -> None:
        self._send(["set_property", "aid", "auto" if bool(enabled) else "no"])

    def set_speed(self, value: float) -> None:
        self._send(["set_property", "speed", min(8.0, max(0.1, float(value)))])

    def set_raw_overlay(
        self,
        overlay_id: int,
        path: str | os.PathLike[str],
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        stride: int,
        display_width: int | None = None,
        display_height: int | None = None,
        pixel_format: str = "bgra",
    ) -> None:
        """Publish one raw bitmap inside mpv's own D3D composition plane.

        Qt alien children cannot reliably paint above an externally rendered
        native ``--wid`` surface on Windows.  The Studio still owns the visual
        and interaction widgets; this command only carries their pixels across
        that native composition boundary.
        """
        command: list[Any] = [
            "overlay-add",
            int(overlay_id),
            int(x),
            int(y),
            str(Path(path).resolve()),
            0,
            str(pixel_format),
            max(1, int(width)),
            max(1, int(height)),
            max(4, int(stride)),
        ]
        if display_width is not None or display_height is not None:
            command.extend([
                max(1, int(display_width or width)),
                max(1, int(display_height or height)),
            ])
        self._send(command)
        self._record_visual_applied(int(overlay_id), True)

    def remove_overlay(self, overlay_id: int) -> None:
        self._send(["overlay-remove", int(overlay_id)])
        self._record_visual_applied(int(overlay_id), False)

    def screenshot_to_file(
        self,
        path: str | os.PathLike[str],
        *,
        mode: str = "window",
    ) -> None:
        """Ask mpv to capture the composed video/subtitle/bitmap plane."""
        self._send(["screenshot-to-file", str(Path(path).resolve()), str(mode)])

    def get_property(self, name: str, default: Any = None) -> Any:
        response = self._send(["get_property", str(name)])
        return response.get("data", default)

    def close(self) -> None:
        self._position_observer=None
        boundary=getattr(self,'_caption_boundary_publisher',None)
        if boundary is not None:boundary.close();self._caption_boundary_publisher=None
        actor = self._actor
        self._actor = None
        if actor is not None:
            actor.close()
        process = self._process
        self._process = None
        self._studio_subtitle_sid = None
        self._studio_subtitle_path = ""
        if process is None:
            if os.name != "nt":
                cleanup_unix_ipc(self._pipe_path)
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=2.0)
        if os.name != "nt":
            cleanup_unix_ipc(self._pipe_path)

    def __enter__(self) -> "MpvController":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def create_preview_controller(canvas=None, *, platform=None):
    """Select Mac's embedded Qt video; Windows retains its mpv/pipe owner."""
    import sys
    if (platform or sys.platform) == 'darwin':
        from ..studio.studio_qt_preview import QtEmbeddedVideoController
        return QtEmbeddedVideoController(canvas)
    return MpvController()
