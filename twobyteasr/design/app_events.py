"""One application-wide event filter shared by every whole-app listener.

2026-11-14. Each object installed with ``QApplication.installEventFilter`` is
called from C++ into Python for every event of every widget. A theme switch or
zoom step sends ~60,000 style/paint/layout events; with five such filters that
was ~300,000 Python calls, 2.4-3.4 s of a 6 s theme switch (measured in a real
window). Listeners here name the event types they handle. Qt calls Python once
per event, and only listeners registered for that type run.

Order follows Qt's: the most recently registered listener runs first, and the
first one that returns True consumes the event. Registering an owner again
moves it to the front, like installing an application filter again. A
listener is dropped when its owner QObject is destroyed.

Short-lived interaction guards that must see input before anything else
(modal dialog guards, window drags) still install their own filter.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

Listener = Callable[[QObject, QEvent], bool]
Registration = tuple[QObject, frozenset[QEvent.Type], Listener]


class AppEventHub(QObject):
    def __init__(self, app):
        super().__init__(app)
        self._owners: dict[int, Registration] = {}
        self._order: list[int] = []  # newest first
        self._by_type: dict[QEvent.Type, tuple[tuple[int, Registration], ...]] = {}

    def listen(self, owner: QObject, types: Iterable[QEvent.Type], listener: Listener | None = None) -> None:
        key = id(owner)
        fresh = key not in self._owners
        self._owners[key] = (owner, frozenset(types), listener or owner.eventFilter)
        if not fresh:
            self._order.remove(key)
        self._order.insert(0, key)
        if fresh:
            owner.destroyed.connect(lambda *_args, key=key: self._drop(key))
        self._rebuild()

    def unlisten(self, owner: QObject) -> None:
        self._drop(id(owner))

    def listening(self, owner: QObject) -> bool:
        return id(owner) in self._owners

    def _drop(self, key: int) -> None:
        if self._owners.pop(key, None) is not None:
            self._order.remove(key)
            self._rebuild()

    def _rebuild(self) -> None:
        # Copy-on-write: a listener may (un)register others while one event is dispatched.
        table: dict[QEvent.Type, list[tuple[int, Registration]]] = {}
        for key in self._order:
            registration = self._owners[key]
            _owner, types, _listener = registration
            for kind in types:
                table.setdefault(kind, []).append((key, registration))
        self._by_type = {kind: tuple(listeners) for kind, listeners in table.items()}

    def eventFilter(self, watched, event):
        listeners = self._by_type.get(event.type())
        if listeners:
            for key, registration in listeners:
                # Earlier callbacks can retire or destroy a later owner. Qt
                # stops calling removed filters within the current event too.
                if self._owners.get(key) is not registration:
                    continue
                if registration[2](watched, event):
                    return True
        return False


def hub(app: QApplication | None = None) -> AppEventHub | None:
    app = app or QApplication.instance()
    if app is None:
        return None
    existing = getattr(app, '_app_event_hub', None)
    if existing is None:
        existing = app._app_event_hub = AppEventHub(app)
        app.installEventFilter(existing)
    return existing


def listen(owner: QObject, types: Iterable[QEvent.Type], listener: Listener | None = None) -> bool:
    shared = hub()
    if shared is None:
        return False
    shared.listen(owner, types, listener)
    return True


def unlisten(owner: QObject) -> None:
    app = QApplication.instance()
    shared = getattr(app, '_app_event_hub', None) if app is not None else None
    if shared is not None:
        shared.unlisten(owner)
