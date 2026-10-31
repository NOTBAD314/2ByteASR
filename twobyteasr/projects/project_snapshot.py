"""Detach document fields without copying live controllers or worker caches."""
from copy import deepcopy
from dataclasses import fields


def document_snapshot(project, *, cues=None):
    """Called by the GUI at a committed boundary; workers own the result.

    Runtime subscribers may contain bound Qt slots, locks and native objects.
    They are not part of the saved document and must never enter deepcopy.
    """
    runtime = getattr(project, '_studio_state_runtime', None)
    if runtime is not None and runtime._active is not None:
        raise RuntimeError('不能在编辑事务提交前创建导出快照')
    from ..timeline.studio_edit_sequence import persist_sequence
    persist_sequence(project)
    clone = object.__new__(type(project))
    clone.__dict__.update({item.name: deepcopy(cues if item.name == 'cues' and cues is not None
                                               else getattr(project, item.name))
                           for item in fields(project)})
    return clone
