"""Language-neutral project naming provenance; never rename files on display."""
from functools import lru_cache
import json
from pathlib import Path
import re

from .i18n import tr


@lru_cache(maxsize=512)
def _read(path, modified, size):
    try:
        payload=json.loads(Path(path).read_text('utf-8'))
        return payload if isinstance(payload,dict) else {}
    except (OSError,ValueError):
        return {}


def display_project_name(record=None, *, path=None, project=None):
    record=record or {}
    path=Path(path or record.get('path') or '')
    name=str(record.get('name') or path.stem)
    payload={}
    if project is None and path.is_file():
        try:
            stat=path.stat()
            payload=_read(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
        except OSError:
            pass
    state=(project.studio_state if project is not None else payload.get('studio_state')) or {}
    # An explicit human rename always wins, even if it looks exactly like a
    # translated/default title. Old releases already recorded this field.
    metadata = project.generation_metadata if project is not None else payload.get('generation_metadata', {})
    timeline = metadata.get('timeline_recognition', {})
    legacy_result = (timeline.get('source_project_id') and timeline.get('source_project_path')
        and state.get('project_name') == f"{Path(timeline['source_project_path']).stem} · 识别结果")
    if state.get('project_name') and not state.get('project_name_automatic') and not legacy_result:
        return str(state['project_name'])
    if record.get('name_custom') and not state:
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
