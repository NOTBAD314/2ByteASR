"""Visual use of the existing enabled glossary; never applies its replacements."""
from dataclasses import replace
from functools import lru_cache
import json
import os
from collections import OrderedDict
import threading

_SNAPSHOTS = OrderedDict()
_SNAPSHOT_LOCK = threading.Lock()
from .terminology import GlossarySnapshot, TermResolver


@lru_cache(maxsize=16)
def resolver(serialized):
    snapshot = GlossarySnapshot.from_dict(json.loads(serialized))
    visual = replace(snapshot, libraries=tuple(replace(library, terms=tuple(
        replace(term, correction_enabled=True) for term in library.terms if term.emphasis_enabled))
        for library in snapshot.libraries))
    return TermResolver(visual)


@lru_cache(maxsize=4096)
def match_marks(text, serialized):
    result = resolver(serialized).resolve(text)
    hits = (*result.hits, *(hit for hit in result.skipped if hit.reason == 'already_canonical'))
    return tuple((hit.start, hit.end) for hit in hits)


def snapshot_active(project=None):
    from .glossary_binding import applied_library_ids
    ids = applied_library_ids(project)[0] if project is not None else ()
    # 2026-10-24 daily port: caption preparation asks this for every revision; a project without a
    # glossary must not import subtitle_core (model paths, seconds on a cold worker) to learn that.
    if project is not None and not ids: return GlossarySnapshot()
    import subtitle_core as legacy
    from .terminology import snapshot_glossaries
    if project is None: ids = legacy.runtime_enabled_glossary_ids()
    if not ids: return GlossarySnapshot()
    stamps=[]
    for name in ('LEARNED_TERMS_PATH','GAME_PROFILES_PATH'):
        path=str(getattr(legacy,name,''))
        try:
            stat=os.stat(path);stamps.append((path,stat.st_mtime_ns,stat.st_size))
        except OSError:stamps.append((path,0,0))
    key=(tuple(ids),tuple(stamps),id(legacy.load_learned_term_payload),id(legacy.load_game_profiles))
    with _SNAPSHOT_LOCK:
        cached=_SNAPSHOTS.get(key)
    if cached is not None:return cached
    result=snapshot_glossaries(legacy,ids)
    with _SNAPSHOT_LOCK:
        _SNAPSHOTS[key]=result
        while len(_SNAPSHOTS)>8:_SNAPSHOTS.popitem(last=False)
    return result


def refresh_visual_glossary(page):
    with _SNAPSHOT_LOCK: _SNAPSHOTS.clear()
    if page is None or page.project is None:
        return
    from .glossary_binding import applied_library_ids
    if not applied_library_ids(page.project)[0]:
        return
    from ..projects.studio_runtime_state import state_for, DirtyDomain
    # A library setting changed, not caption text or the user's project file.
    with state_for(page.project).transaction(page.project, action_id='glossary_visual_settings_changed',
        dirty=DirtyDomain.CUE_STYLE|DirtyDomain.NATIVE_SUBTITLE|DirtyDomain.ADVANCED_PREVIEW,
        affected_cue_ids=(cue.id for cue in page.project.cues)):
        pass


def visual_cues(cues, snapshot):
    from copy import deepcopy
    serialized = json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True)
    result = []
    for cue in cues:
        # A freely authored AI theme owns its visual rules. This data is only
        # consumed by the ordinary text renderer (WebTheme ignores text_marks).
        spans = match_marks(cue.text, serialized)
        if not spans:
            result.append(cue)
            continue
        shown = deepcopy(cue)
        auto = [dict(start=a,end=b,highlight=True) for a,b in spans]
        shown.appearance_override['text_marks'] = auto + list(cue.appearance_override.get('text_marks', []))
        result.append(shown)
    return result
