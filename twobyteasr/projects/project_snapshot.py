"""Detach document fields without copying live controllers or worker caches."""
from copy import deepcopy
from dataclasses import fields
import marshal


def copy_json_value(value, *, field='value'):
    """Detach in-memory JSON-shaped metadata without per-leaf Python deepcopy.

    No bytes from files or IPC are decoded here. Built-in containers are
    copied by marshal in one C call: no ``__deepcopy__``/``__reduce_ex__``
    hooks run and the GIL is not handed to other threads halfway through
    (2026-11-19: export start spent >2 s in a per-node deepcopy of a large
    studio_state on the GUI thread, then died with an access violation inside
    deepcopy). Anything marshal refuses goes through ``_detach``: Qt value
    types become plain values, a live Qt object is refused with the field
    name, other legacy runtime values keep the existing deepcopy behavior.
    """
    try:
        return marshal.loads(marshal.dumps(value,4))
    except (TypeError,ValueError):
        return _detach(value, field, {})


_ATOMIC = (str, int, float, bool, bytes, type(None))


def _detach(value, path, memo):
    if type(value) in _ATOMIC:
        return value
    key = id(value)
    if key in memo:
        return memo[key]
    kind = type(value)
    if kind is dict:
        result = memo[key] = {}
        for name, item in value.items():
            result[name] = _detach(item, f'{path}.{name}', memo)
        return result
    if kind is list:
        result = memo[key] = []
        result.extend(_detach(item, f'{path}[{index}]', memo) for index, item in enumerate(value))
        return result
    if kind is tuple:
        result = memo[key] = tuple(_detach(item, f'{path}[{index}]', memo) for index, item in enumerate(value))
        return result
    if _is_qt(kind):
        result = memo[key] = _qt_plain(value, path)
        return result
    return deepcopy(value, memo)


def _is_qt(kind):
    return any(str(getattr(base, '__module__', '')).startswith(('PySide6', 'shiboken6'))
               for base in kind.__mro__)


def _qt_plain(value, path):
    """Plain JSON form of a Qt value type; a live Qt object is refused.

    Copying a wrapper reaches into its C++ object (possibly deleted, or owned
    by a worker thread), so project data may only hold plain values.
    """
    import enum
    if isinstance(value, enum.Enum):
        raw = value.value
        return raw if type(raw) in _ATOMIC else int(raw)
    from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QSizeF
    from PySide6.QtGui import QColor, QFont
    if isinstance(value, QColor):
        if not value.isValid():
            return ''
        fmt = QColor.NameFormat.HexArgb if value.alpha() < 255 else QColor.NameFormat.HexRgb
        return value.name(fmt)
    if isinstance(value, (QPoint, QPointF)):
        return [value.x(), value.y()]
    if isinstance(value, (QSize, QSizeF)):
        return [value.width(), value.height()]
    if isinstance(value, (QRect, QRectF)):
        return [value.x(), value.y(), value.width(), value.height()]
    if isinstance(value, QFont):
        return value.toString()
    from .studio_project import ProjectValidationError
    raise ProjectValidationError(
        f'{path} holds a live Qt object ({type(value).__name__}); '
        'project data must be plain JSON values')


def presentation_snapshot(project, *, cue_ids=None):
    """Detached render inputs, with evidence limited to the selected captions.

    Selection geometry consumes one caption. It must not clone recognition
    histories, source archives, runtime subscribers, or an entire document.
    """
    from .studio_project import SubtitleProject
    from ..timeline.studio_caption_timeline import KEY
    cues=[cue for cue in project.cues if cue_ids is None or cue.id in cue_ids]
    ids={cue.id for cue in cues}
    refs={ref for cue in cues for ref in cue.evidence_refs}
    refs.update('cue-align:'+key for key in ids)
    state={key:value for key,value in project.studio_state.items() if key not in
           {KEY,'term_word_overrides','glossary_proofread_review','manual_caption_text'}}
    timeline=project.studio_state.get(KEY)
    if isinstance(timeline,dict):
        state[KEY]={key:value for key,value in timeline.items() if key not in {'instances','source_archive'}}
        state[KEY]['instances']={key:value for key,value in timeline.get('instances',{}).items() if key in ids}
    state['term_word_overrides']={key:value for key,value in project.studio_state.get('term_word_overrides',{}).items() if key in ids}
    metadata={key:value for key,value in project.generation_metadata.items() if key in
              {'language','source_language','speaker_names','glossary_binding','applied_glossaries','glossary_snapshot','terminology_snapshot'}}
    metadata['translations']={key:value for key,value in project.generation_metadata.get('translations',{}).items() if key in ids}
    clone=SubtitleProject(media=deepcopy(project.media),cues=deepcopy(cues),speakers=deepcopy(project.speakers),
        styles=deepcopy(project.styles),effects=deepcopy(project.effects),style_recipes=deepcopy(project.style_recipes),
        render_settings=deepcopy(project.render_settings),studio_state=deepcopy(state),generation_metadata=deepcopy(metadata),
        asr_evidence=deepcopy({key:value for key,value in project.asr_evidence.items() if key in refs}),
        glossary_ids=list(project.glossary_ids),project_id=project.project_id)
    return clone


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
    for item in fields(project):
        value = cues if item.name == 'cues' and cues is not None else getattr(project, item.name)
        # Records (media, tracks, cues, styles) keep their own __deepcopy__;
        # JSON fields (studio_state, evidence, metadata) are copied in one C
        # call instead of millions of GIL-yielding Python steps.
        clone.__dict__[item.name] = (copy_json_value(value, field=item.name)
                                     if isinstance(value, dict) or item.name == 'edit_history'
                                     else deepcopy(value))
    return clone
