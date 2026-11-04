"""Commit owned Qt child HWND visibility after a synchronous page handoff.

Qt show/hide events and logical visibility still happen immediately. A scope
only postpones native SHOW/HIDE flags for already-created, explicitly bound
widgets. It never creates windows, reparents them, or handles external players.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import ctypes
from ctypes import wintypes as W
from dataclasses import dataclass
import os
import sys
import weakref

from PySide6.QtCore import QAbstractNativeEventFilter, QThread, Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


_CHANGING = 0x0046
_DESTROY = 0x0082
_SHOW = 0x0040
_HIDE = 0x0080
_VISIBLE = 0x10000000
_STABLE = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0200
_DEFAULT = object()


class _WindowPos(ctypes.Structure):
    _fields_ = [("hwnd", W.HWND), ("hwndInsertAfter", W.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", W.UINT)]


@dataclass(frozen=True)
class _Identity:
    hwnd: int
    parent: int
    pid: int
    thread: int
    window_class: str
    is_child: bool = True


@dataclass
class _Binding:
    identity: _Identity
    widget: object


class _Win32Visibility:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        for name, args, result in (
            ("IsWindow", [W.HWND], W.BOOL),
            ("GetParent", [W.HWND], W.HWND),
            ("GetWindowThreadProcessId", [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            ("GetClassNameW", [W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
            ("GetWindowLongPtrW", [W.HWND, ctypes.c_int], ctypes.c_ssize_t),
            ("BeginDeferWindowPos", [ctypes.c_int], W.HANDLE),
            ("DeferWindowPos", [W.HANDLE, W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, W.UINT], W.HANDLE),
            ("EndDeferWindowPos", [W.HANDLE], W.BOOL),
            ("SetWindowPos", [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
        ):
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result

    def identity(self, hwnd):
        if not hwnd or not self.user.IsWindow(hwnd):
            return None
        pid = W.DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ctypes.create_unicode_buffer(256)
        if not thread or not self.user.GetClassNameW(hwnd, name, len(name)):
            return None
        return _Identity(int(hwnd), int(self.user.GetParent(hwnd) or 0),
                         int(pid.value), int(thread), name.value,
                         bool(self.user.GetWindowLongPtrW(hwnd, -16) & 0x40000000))

    def visible_style(self, hwnd):
        # IsWindowVisible also considers ancestors; commit each HWND's own bit.
        return bool(self.user.GetWindowLongPtrW(hwnd, -16) & _VISIBLE)

    def batch(self, targets):
        if len({info.parent for info, _visible in targets}) != 1:
            raise ValueError("A native visibility batch requires one parent")
        if any(self.identity(info.hwnd) != info for info, _visible in targets):
            raise RuntimeError("Native visibility identity changed before batch")
        hdwp = self.user.BeginDeferWindowPos(len(targets))
        if not hdwp:
            raise ctypes.WinError(ctypes.get_last_error())
        for info, visible in targets:
            hdwp = self.user.DeferWindowPos(hdwp, info.hwnd, None, 0, 0, 0, 0,
                _STABLE | (_SHOW if visible else _HIDE))
            if not hdwp:
                # Win32 invalidates the HDWP on failure. Do not call End.
                raise ctypes.WinError(ctypes.get_last_error())
        if not self.user.EndDeferWindowPos(hdwp):
            raise ctypes.WinError(ctypes.get_last_error())

    def set_visibility(self, info, visible):
        if self.identity(info.hwnd) != info:
            return False
        return bool(self.user.SetWindowPos(info.hwnd, None, 0, 0, 0, 0,
                    _STABLE | (_SHOW if visible else _HIDE)))


def _ordered_groups(targets, ancestry):
    """Same-parent batches with children prepared before a parent is shown.

    Hiding an ancestor runs first, making later child changes invisible. Showing
    it runs last. A common-parent batch can hide the old page and show the new
    one together after the new subtree has been prepared.
    """
    groups = {}
    by_hwnd = {binding.identity.hwnd: (binding, visible) for binding, visible in targets}
    for binding, visible in targets:
        groups.setdefault(binding.identity.parent, []).append((binding, visible))
    edges = {parent: set() for parent in groups}
    for binding, _visible in targets:
        child_group = binding.identity.parent
        for ancestor in ancestry[binding.identity.hwnd]:
            if ancestor not in by_hwnd:
                continue
            parent_binding, parent_visible = by_hwnd[ancestor]
            parent_group = parent_binding.identity.parent
            if child_group == parent_group:
                continue
            before, after = ((child_group, parent_group) if parent_visible
                             else (parent_group, child_group))
            edges[after].add(before)
    ordered = []
    while edges:
        ready = [parent for parent, dependencies in edges.items() if not dependencies]
        if not ready:
            raise RuntimeError("Inconsistent native visibility hierarchy")
        for parent in ready:
            ordered.append(groups[parent])
            del edges[parent]
            for dependencies in edges.values():
                dependencies.discard(parent)
    return ordered


class NativeVisibilityCommit(QAbstractNativeEventFilter):
    """GUI-thread ``scope(widgets)`` for one owner's native Qt handoffs.

    Use the same instance for nested scopes. Pass every native ancestor whose
    visibility will change as well as the native descendants. Ordinary widgets
    and not-yet-created handles are ignored. The caller paints the target page
    inside the scope; this class does not paint, pump events, or wait.

    ``close()`` retires pending work without restoring or creating handles.
    ``last_result`` reports a failed batch/fallback; failure is not disguised as
    an atomic commit. ``after_commit(receipt)`` runs once after the outermost
    native commit and binding cleanup. Its result/error is recorded separately
    under ``post_commit``; native commit success is not screen presentation.
    Closed and unsupported scopes do not call it. Non-Windows/offscreen
    applications use a no-op scope.
    """
    def __init__(self, owner=None, *, after_commit=None, _api=_DEFAULT, _application=None):
        super().__init__()
        self._app = _application if _application is not None else QApplication.instance()
        if _api is _DEFAULT:
            _api = (_Win32Visibility() if sys.platform == "win32" and self._app
                    and self._app.platformName() == "windows" else None)
        self._api = _api
        self._pid = os.getpid()
        self._bindings = {}
        self._pending = set()
        self._depth = 0
        self._installed = False
        self._closed = False
        self._committing = False
        self.after_commit = after_commit
        self.last_result = {"status": "idle"}
        if owner is not None:
            owner.destroyed.connect(self.close)

    def _assert_gui_thread(self):
        if self._app is None or not isValid(self._app):
            raise RuntimeError("Native visibility scopes require a live QApplication")
        if QThread.currentThread() != self._app.thread():
            raise RuntimeError("Native visibility scopes must run on the GUI thread")

    def _error(self, error):
        errors = self.last_result.setdefault("errors", [])
        if len(errors) < 8:
            errors.append(str(error))

    def _bind(self, widget):
        if widget is None or not isValid(widget):
            return
        # GetParent(top-level HWND) can return its owner, not a native parent.
        if widget.isWindow():
            return
        if not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return
        hwnd = int(widget.internalWinId() or 0)
        info = self._api.identity(hwnd)
        if info is None or info.pid != self._pid or not info.parent or not info.is_child:
            return
        existing = self._bindings.get(hwnd)
        if existing and (existing.identity != info or existing.widget() is not widget):
            self._pending.discard(hwnd)
        self._bindings[hwnd] = _Binding(info, weakref.ref(widget))

    def _current(self, binding):
        info = binding.identity
        if (self._closed or self._bindings.get(info.hwnd) is not binding
                or self._api.identity(info.hwnd) != info):
            return None
        widget = binding.widget()
        if widget is None or not isValid(widget):
            return None
        if widget.isWindow():
            return None
        if int(widget.internalWinId() or 0) != info.hwnd:
            return None
        return widget

    @contextmanager
    def scope(self, widgets=()):
        self._assert_gui_thread()
        if self._closed or self._api is None or self._committing:
            yield self
            return
        if self._depth == 0:
            self.last_result = {"status": "holding", "deferred_messages": 0,
                                "batches": [], "errors": []}
        self._depth += 1
        try:
            for widget in widgets:
                self._bind(widget)
            if self._bindings and not self._installed:
                self._app.installNativeEventFilter(self)
                self._installed = True
            yield self
        finally:
            self._depth -= 1
            if self._depth == 0:
                # The native commit must never be intercepted by this filter.
                self._uninstall()
                completed = None
                try:
                    if not self._closed:
                        self._commit()
                        completed = self.last_result
                finally:
                    self._bindings.clear()
                    self._pending.clear()
                # Do not retain old bindings while the caller flushes. A Qt
                # callback may navigate again; that is a separate transaction.
                if completed is not None and not self._closed:
                    self._notify_after_commit(completed)

    def _notify_after_commit(self, receipt):
        callback = self.after_commit
        if not callable(callback):
            return
        if not receipt.get("batches") and not receipt.get("reconcile") and receipt.get("status") == "committed":
            receipt["post_commit"] = {"status": "not_needed", "reason": "no_native_visibility_changes"}
            return
        # Copy the receipt so a callback cannot rewrite native success/failure
        # evidence. Likewise do not expose a mutable result owned by the caller.
        observation = {"status": "running"}
        snapshot = deepcopy(receipt)
        receipt["post_commit"] = observation
        try:
            result = callback(snapshot)
            observation.update(status="completed", result=deepcopy(result))
        except Exception as error:
            # Never mask an exception from the scope body or mislabel a failed
            # native commit as successful because a fallback callback ran.
            observation.update(status="error", error=f"{type(error).__name__}: {error}")

    def _uninstall(self):
        installed, self._installed = self._installed, False
        if installed and self._app is not None and isValid(self._app):
            self._app.removeNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        # No QWidget/QObject calls in this callback, including on destruction.
        if not self._installed or self._closed or self._depth <= 0:
            return False, 0
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            msg = W.MSG.from_address(int(message))
            hwnd = int(msg.hWnd or 0)
            binding = self._bindings.get(hwnd)
            if binding is None:
                return False, 0
            if binding.widget() is None:
                self._bindings.pop(hwnd, None)
                self._pending.discard(hwnd)
                return False, 0
            if msg.message == _DESTROY:
                self._bindings.pop(hwnd, None)
                self._pending.discard(hwnd)
            elif msg.message == _CHANGING and msg.lParam:
                pos = _WindowPos.from_address(int(msg.lParam))
                if (int(pos.hwnd or 0) == hwnd and pos.flags & (_SHOW | _HIDE)
                        and self._api.identity(hwnd) == binding.identity):
                    self._pending.add(hwnd)
                    pos.flags &= ~(_SHOW | _HIDE)
                    self.last_result["deferred_messages"] += 1
        except Exception as error:
            self._error(error)
        return False, 0

    def _commit(self):
        self._committing = True
        try:
            targets, ancestry = [], {}
            for hwnd in self._pending:
                binding = self._bindings.get(hwnd)
                widget = self._current(binding) if binding else None
                if widget is None:
                    continue
                visible = widget.isVisible()
                if self._api.visible_style(hwnd) == visible:
                    continue
                targets.append((binding, visible))
                chain, ancestor = [], binding.identity.parent
                while ancestor:
                    if ancestor in chain or len(chain) >= 64:
                        raise RuntimeError("Invalid native parent chain")
                    chain.append(ancestor)
                    info = self._api.identity(ancestor)
                    ancestor = info.parent if info else 0
                ancestry[hwnd] = chain
            for group in _ordered_groups(targets, ancestry):
                current = []
                for binding, _visible in group:
                    widget = self._current(binding)
                    if widget is not None:
                        visible = widget.isVisible()
                        if self._api.visible_style(binding.identity.hwnd) != visible:
                            current.append((binding.identity, visible))
                if not current:
                    continue
                receipt = {"parent": current[0][0].parent,
                           "targets": [{"hwnd": info.hwnd, "visible": visible}
                                       for info, visible in current], "ok": False}
                self.last_result["batches"].append(receipt)
                self._api.batch(current)
                receipt["ok"] = True
            self.last_result["status"] = ("closed" if self._closed
                                           else "error" if self.last_result["errors"] else "committed")
        except Exception as error:
            self._error(error)
            # Any failure, including planning/identity reads, gets one guarded
            # reconciliation pass. The filter is already removed. This is
            # explicitly degraded, never reported as an atomic success.
            reconciled = self._reconcile_pending()
            self.last_result["status"] = ("closed" if self._closed
                                           else "fallback" if reconciled else "error")
        finally:
            self._committing = False

    def _reconcile_pending(self):
        rows = self.last_result["reconcile"] = []
        candidates = []
        ok = True
        for hwnd in tuple(self._pending):
            try:
                binding = self._bindings.get(hwnd)
                widget = self._current(binding) if binding else None
                if widget is None:
                    continue
                visible = widget.isVisible()
                if self._api.visible_style(hwnd) == visible:
                    continue
                ancestors, parent = set(), binding.identity.parent
                while parent and parent not in ancestors and len(ancestors) < 64:
                    ancestors.add(parent)
                    info = self._api.identity(parent)
                    parent = info.parent if info else 0
                candidates.append((visible, -len(ancestors) if visible else len(ancestors), binding))
            except Exception as error:
                ok = False
                self._error(error)
        for _visible, _depth, binding in sorted(candidates, key=lambda item: item[:2]):
            try:
                widget = self._current(binding)
                if widget is None:
                    continue
                visible = widget.isVisible()
                applied = bool(self._api.set_visibility(binding.identity, visible))
                rows.append({"hwnd": binding.identity.hwnd, "visible": visible, "ok": applied})
                ok = applied and ok
            except Exception as error:
                ok = False
                self._error(error)
        return ok

    def close(self, *_args):
        self._closed = True
        self._pending.clear()
        self._bindings.clear()
        self._uninstall()
        self.last_result["status"] = "closed"
