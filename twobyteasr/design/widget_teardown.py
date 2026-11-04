"""Let Python's cycle collector drop a widget tree without a double delete.

2026-10-14: a parentless dialog or combo dropped in a reference cycle (its
WindowBounds, the combo <-> popup attributes, bound methods ...) is destroyed
by the cycle collector, which clears its wrappers one by one in generation
order. Shiboken (6.9.2 here, unchanged up to 6.11.0) hands a cleared wrapper's
C++ object to Python when the wrapper still has a parent (``tp_clear`` ->
``removeParent(giveOwnershipBack=true)``), even for objects Qt owns: the
``QWidgetItem`` wrappers that
``addLayout()`` creates for an already filled sub-layout, the list's
``verticalScrollBar()``, the ``QScreen`` from ``widget.screen()``. Cleared
before their parents, they are deleted by Python and then again by Qt
(0xC0000374 on Windows, SIGSEGV on macOS); which wrapper goes first depends
on what the generations hold, so it came and went with the bytecode cache.

The collector calls every finalizer (``__del__``) before it clears anything.
A top-level widget therefore deletes its C++ tree there, in Qt's order as
``deleteLater()`` would; afterwards every wrapper in the cycle is invalid and
clearing it deletes nothing.
"""
from __future__ import annotations

import threading

_deferred: list = []


def delete_tree_before_collection(widget) -> None:
    """``__del__`` for widgets that may be the top of a collected cycle."""
    try:
        import shiboken6
        if not shiboken6.isValid(widget) or not shiboken6.ownedByPython(widget):
            return  # already deleted, or a Qt parent deletes it with its own tree
        if threading.current_thread() is threading.main_thread():
            shiboken6.delete(widget)
            return
        # Collections also run on worker threads. Widgets must die on the GUI
        # thread: keep this one alive (the collector then leaves the whole
        # cycle alone) and delete it there.
        from PySide6.QtCore import QCoreApplication, QTimer
        app = QCoreApplication.instance()
        if app is not None:
            _deferred.append(widget)
            QTimer.singleShot(0, app, _delete_deferred)
    except Exception:
        pass  # interpreter shutdown: shiboken6/PySide6 may already be gone


def _delete_deferred() -> None:
    import shiboken6
    while _deferred:
        widget = _deferred.pop()
        if shiboken6.isValid(widget) and shiboken6.ownedByPython(widget):
            shiboken6.delete(widget)
