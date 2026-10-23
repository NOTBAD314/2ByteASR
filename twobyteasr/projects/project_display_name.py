"""Language-neutral project naming provenance; never rename files on display."""
from functools import lru_cache
import json
from pathlib import Path
import re

from ..i18n import tr


_NAME_KEYS=('project_name','project_name_automatic','project_name_origin')


_READ_KEYS: set = set()


@lru_cache(maxsize=512)
def _read(path, modified, size):
    """Only the naming fields of a project file.

    2026-10-22: this cache held up to 512 whole parsed projects (the user's
    library: 456 files, 462 MB of JSON) for the life of the process."""
    _READ_KEYS.add((path, modified, size))
    if len(_READ_KEYS) > 500:  # the lru_cache below keeps 512
        _READ_KEYS.clear()
    try:
        payload=json.loads(Path(path).read_text('utf-8'))
    except (OSError,ValueError):
        return {}
    if not isinstance(payload,dict):
        return {}
    state=payload.get('studio_state') or {}
    metadata=payload.get('generation_metadata') or {}
    timeline=metadata.get('timeline_recognition') or {} if isinstance(metadata,dict) else {}
    media=payload.get('media') or {}
    return {'studio_state':{key:state[key] for key in _NAME_KEYS if isinstance(state,dict) and key in state},
            'state_present':bool(state),
            'generation_metadata':{'timeline_recognition':{key:timeline[key] for key in
                ('source_project_id','source_project_path') if isinstance(timeline,dict) and key in timeline}},
            'media':{'path':media.get('path')} if isinstance(media,dict) else {}}


def _read_key(path):
    try:
        stat=path.stat()
        return str(path.resolve()),stat.st_mtime_ns,stat.st_size
    except OSError:
        return None


def name_needs_read(record=None, *, path=None) -> bool:
    """True if the exact name still needs the project file read."""
    record=record or {}
    path=Path(path or record.get('path') or '')
    key=_read_key(path) if path.is_file() else None
    return key is not None and key not in _READ_KEYS


def display_project_name(record=None, *, path=None, project=None, read=True):
    """``read=False``: never parse the project file here; until it has been
    read once (``name_needs_read``) the library index's name is used.
    2026-10-22: the project library read each card's whole file (up to tens of
    MB) on the GUI thread just for this."""
    record=record or {}
    path=Path(path or record.get('path') or '')
    name=str(record.get('name') or path.stem)
    payload={}
    if project is None and path.is_file():
        key=_read_key(path)
        if key is not None and (read or key in _READ_KEYS):
            payload=_read(*key)
    state=(project.studio_state if project is not None else payload.get('studio_state')) or {}
    # An explicit human rename always wins, even if it looks exactly like a
    # translated/default title. Old releases already recorded this field.
    metadata = project.generation_metadata if project is not None else payload.get('generation_metadata', {})
    timeline = metadata.get('timeline_recognition', {})
    legacy_result = (timeline.get('source_project_id') and timeline.get('source_project_path')
        and state.get('project_name') == f"{Path(timeline['source_project_path']).stem} · 识别结果")
    if state.get('project_name') and not state.get('project_name_automatic') and not legacy_result:
        return str(state['project_name'])
    state_present=bool(project.studio_state) if project is not None else bool(payload.get('state_present'))
    if record.get('name_custom') and not state_present:
        return name
    origin=state.get('project_name_origin') or record.get('name_origin') or {}
    if not origin and legacy_result:
        origin={'kind':'recognition_result','parent':Path(timeline['source_project_path']).stem}
    if not origin and (payload or project is not None):
        media=(vars(project.media) if project is not None else payload.get('media')) or {}
        match=re.fullmatch(r'未命名工程(?: ([2-9]|[1-9]\d+))?',path.stem)
        # Legacy blank-project allocation had this exact parent/file pair and
        # no project_name. A media-derived title of the same spelling stays data.
        if match and path.parent.name==path.stem and not state.get('project_name'):
            media_name=Path(str(media.get('path') or '')).stem
            if media_name != path.stem:
                origin={'kind':'unnamed','number':int(match[1]) if match[1] else None}
        if path.stem=='识别结果' and timeline.get('source_project_id'):
            origin={'kind':'recognition_result'}
    if origin.get('kind')=='unnamed':
        number=origin.get('number')
        return tr('未命名工程 {number}',number=number) if number is not None else tr('未命名工程')
    if origin.get('kind')=='recognition_result':
        parent=origin.get('parent')
        return tr('{name} · 识别结果',name=parent) if parent else tr('识别结果')
    return str(state.get('project_name') or name)
