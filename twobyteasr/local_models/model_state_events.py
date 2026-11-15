"""App-owned state notifications; no polling of directory mtimes as an event bus."""
_bus = None
_tasks = {}


def bus():
    global _bus
    if _bus is None:
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QApplication
        class StateEvents(QObject):
            changed = Signal(object)
        _bus = StateEvents(QApplication.instance())
    return _bus


def notify(keys, reason='changed'):
    if _bus is not None:
        _bus.changed.emit(dict(keys=tuple(keys), reason=reason))


def task_transition(owner, keys, phase, *, active, operation='prepare', outcome=''):
    token=owner if isinstance(owner,str) else str(id(owner))
    value=dict(id=token,keys=tuple(keys),phase=str(phase),active=bool(active),operation=operation,outcome=outcome)
    if _tasks.get(token)!=value:
        _tasks[token]=value
        while len(_tasks)>64:_tasks.pop(next(iter(_tasks)))
        notify(keys,'task_phase')


def active_task(key):
    return next((dict(t) for t in reversed(list(_tasks.values())) if t['active'] and key in t['keys']),None)
