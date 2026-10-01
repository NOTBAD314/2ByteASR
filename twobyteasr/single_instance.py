"""Pingable single-instance ownership for the desktop application."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _local_endpoint(name: str) -> str:
    """AppContainer pipes must use LOCAL; ordinary desktop names stay stable."""
    from .windows_ipc import in_app_container
    return 'LOCAL\\'+name if in_app_container() else name


class SingleInstanceGuard(QObject):
    """Own a local endpoint and distinguish a live GUI from a stale endpoint."""

    paths_received = Signal(list)
    MAX_MESSAGE = 1024 * 1024

    PING = b"2byteasr-ping\n"
    PONG = b"2byteasr-pong\n"

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = str(name)
        self.endpoint = _local_endpoint(self.name)
        self.server = QLocalServer(self)
        # The container's default DACL includes its restricted SID. Replacing it
        # with a desktop user-only DACL makes CreateNamedPipe fail (AccessDenied).
        if self.endpoint == self.name:
            self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._answer_pending_connections)
        self._owns_endpoint = False
        self._mutex_handle: int | None = None
        self._last_owner_responded = False
        self._requests = []
        self._seen_requests = {}
        self._buffers = {}
        self._receiver_ready = False

    @classmethod
    def application_name(cls, root: str | Path | None = None) -> str:
        installation = Path(root or Path(__file__).resolve().parents[1])
        try:
            identity = str(installation.resolve()).casefold()
        except (OSError, ValueError):
            identity = str(installation).casefold()
        if os.environ.get('TWOBYTEASR_TEST_ROOT'):
            from .test_isolation import isolation_root
            identity += '|profile:' + str(isolation_root()).casefold()
        # Verified isolated acceptance runs own an endpoint. They must never
        # forward a test project to another source or frozen GUI instance.
        if os.environ.get('TWOBYTEASR_ACCEPTANCE_DIR'):
            from .studio_acceptance_audit import audit_directory
            output = audit_directory()
            if output is not None:identity += '|acceptance:'+str(output).casefold()
        suffix = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:12]
        return f"2ByteASR-{suffix}"

    def acquire(self, *, connect_timeout_ms: int = 250) -> bool:
        role = str(os.environ.get("TWOBYTEASR_PROCESS_ROLE") or "main-gui")
        if role != "main-gui":
            return False
        if self._owns_endpoint:
            return True
        if os.name == "nt" and not self._acquire_windows_mutex():
            self._last_owner_responded = self._live_owner_responds(
                connect_timeout_ms
            )
            return False
        if os.name != "nt" and self._live_owner_responds(connect_timeout_ms):
            self._last_owner_responded = True
            return False
        QLocalServer.removeServer(self.endpoint)
        if self.server.listen(self.endpoint):
            self._owns_endpoint = True
            return True
        self._release_windows_mutex()
        return False

    def release(self) -> None:
        if not self._owns_endpoint:
            return
        self._owns_endpoint = False
        self.server.close()
        QLocalServer.removeServer(self.endpoint)
        self._release_windows_mutex()

    def _acquire_windows_mutex(self) -> bool:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.CreateMutexW(
            None, False, f"Local\\{self.name}-gui-owner"
        )
        if not handle:
            return False
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        self._mutex_handle = int(handle)
        return True

    def _release_windows_mutex(self) -> None:
        if self._mutex_handle is None or os.name != "nt":
            return
        import ctypes

        handle = self._mutex_handle
        self._mutex_handle = None
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle(ctypes.c_void_p(handle))

    def _live_owner_responds(self, timeout_ms: int) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.endpoint)
        if not socket.waitForConnected(max(1, int(timeout_ms))):
            socket.abort()
            return False
        socket.write(self.PING)
        socket.flush()
        socket.waitForBytesWritten(max(1, int(timeout_ms)))
        if not socket.waitForReadyRead(max(1, int(timeout_ms))):
            socket.abort()
            return False
        response = bytes(socket.readAll())
        socket.disconnectFromServer()
        return self.PONG in response

    def enable_receiver(self):
        self._receiver_ready = True
        pending, self._requests = self._requests, []
        for paths in pending:
            self.paths_received.emit(paths)

    def forward(self, paths, *, timeout_ms=1500, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        payload = json.dumps({"version": 1, "id": request_id, "paths": list(paths)},
                             ensure_ascii=False).encode("utf-8") + b"\n"
        if len(payload) > self.MAX_MESSAGE:
            return False
        socket = QLocalSocket()
        deadline = time.monotonic() + timeout_ms / 1000
        remaining = lambda: max(1, int((deadline - time.monotonic()) * 1000))
        socket.connectToServer(self.endpoint)
        if not socket.waitForConnected(remaining()):
            socket.abort()
            return False
        if os.name == "nt":
            socket.write(b"OWNER\n")
            socket.flush()
            if socket.bytesAvailable() or socket.waitForReadyRead(remaining()):
                try:
                    owner_pid = int(bytes(socket.readAll()).strip())
                    import ctypes
                    ctypes.windll.user32.AllowSetForegroundWindow(owner_pid)
                except (ValueError, OSError):
                    pass
        socket.write(payload)
        socket.flush()
        response = bytearray()
        while time.monotonic() < deadline:
            if socket.bytesAvailable() or socket.waitForReadyRead(remaining()):
                response.extend(bytes(socket.readAll()))
                if b"\n" in response:
                    break
            else:
                break
        socket.abort()
        try:
            reply = json.loads(response.split(b"\n", 1)[0])
            return reply.get("accepted") is True and reply.get("id") == request_id
        except (ValueError, TypeError):
            return False

    def _answer_pending_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.disconnected.connect(lambda current=socket: self._forget_socket(current))
            socket.readyRead.connect(lambda current=socket: self._answer_socket(current))
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(5000)
            if socket.bytesAvailable():
                self._answer_socket(socket)

    def _forget_socket(self, socket):
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _answer_socket(self, socket: QLocalSocket) -> None:
        request = self._buffers.setdefault(socket, bytearray())
        request.extend(bytes(socket.readAll()))
        if len(request) > self.MAX_MESSAGE:
            socket.abort()
            return
        if b"\n" not in request:
            return
        line = bytes(request).split(b"\n", 1)[0]
        if line == b"OWNER":
            request.clear()
            socket.write(str(os.getpid()).encode("ascii") + b"\n")
            socket.flush()
            return
        if line + b"\n" == self.PING:
            response = self.PONG
        else:
            try:
                payload = json.loads(line)
                paths, request_id = payload["paths"], payload["id"]
                if (payload.get("version") != 1 or not isinstance(request_id, str)
                    or not 1 <= len(request_id) <= 64 or not isinstance(paths, list)
                    or len(paths) > 4096 or any(not isinstance(p, str) or "\0" in p for p in paths)):
                    raise ValueError("invalid request")
                if request_id not in self._seen_requests:
                    if not self._receiver_ready and len(self._requests) >= 64:
                        raise ValueError("startup queue full")
                    self._seen_requests[request_id] = True
                    if len(self._seen_requests) > 1024:
                        self._seen_requests.pop(next(iter(self._seen_requests)))
                    if self._receiver_ready:
                        self.paths_received.emit(paths)
                    else:
                        self._requests.append(paths)
                response = json.dumps({"id": request_id, "accepted": True}).encode() + b"\n"
            except (ValueError, KeyError, TypeError):
                response = b'{"accepted":false}\n'
        socket.write(response)
        socket.flush()
        socket.disconnectFromServer()

    @property
    def owns_endpoint(self) -> bool:
        return self._owns_endpoint

    @property
    def last_owner_responded(self) -> bool:
        return self._last_owner_responded


__all__ = ["SingleInstanceGuard"]
