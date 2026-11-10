"""Confirmation authority and short, reentrant locks for glossary JSON writers."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

AUTO_ORIGIN = "Studio 手动修改（自动记入）"
_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()
_held = threading.local()


def requires_review(row):
    if row.get("review_status") in {"pending", "ignored"} or row.get("status") in {"pending", "collecting", "ignored"}:
        return True
    return row.get("origin") == AUTO_ORIGIN and not row.get("confirmation_action")


def suspected_legacy(row):
    """Unknown provenance is a review suggestion, never an automatic demotion."""
    if requires_review(row) or row.get("confirmation_action"):
        return False
    origin = str(row.get("origin") or "")
    return bool(row.get("confirmed")) and origin not in {
        "手动", "批量导入", "用户确认", "官方"
    } and "用户确认" not in origin


@contextmanager
def storage_lock(path):
    """Fail promptly on contention. Caption editing handles this as a missed sample."""
    key = str(Path(path).resolve())
    with _guard:
        mutex = _locks.setdefault(key, threading.RLock())
    if not mutex.acquire(blocking=False):
        raise OSError("词库正在写入，请稍后重试")
    held = getattr(_held, "paths", None)
    if held is None:
        held = _held.paths = set()
    lock = None
    try:
        if key not in held:
            from PySide6.QtCore import QLockFile
            Path(key).parent.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(key + ".lock")
            if not lock.tryLock(0):
                raise OSError("词库正在被另一进程写入，请稍后重试")
            held.add(key)
        yield
    finally:
        if lock is not None and lock.isLocked():
            held.discard(key)
            lock.unlock()
        mutex.release()
