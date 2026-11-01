"""Runtime text addresses over existing cue IDs, import tracks and translation records.

No row-number pairing and no new persisted project format. A generated translation
has the same owner cue as its source, but a distinct address and review key.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
import json


@dataclass(frozen=True)
class TextTarget:
    cue_id: str
    layer: str
    language: str
    track_id: str
    storage: str = "cue"

    @property
    def key(self):
        if self.storage == "cue":
            return self.cue_id
        return "translation:" + json.dumps([self.cue_id, self.language, self.track_id], ensure_ascii=False, separators=(",", ":"))

    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)


@dataclass(frozen=True)
class TextEntry:
    target: TextTarget
    text: str
    start_ms: int
    end_ms: int
    speaker_id: str
    source_text: str = ""
    source_cue_id: str = ""

    @property
    def key(self):
        return self.target.key


def text_entries(project, *, mode="both", tracks=None, cue_ids=None, include_empty=False):
    """Enumerate stored text once. Hidden/collapsed presentation is irrelevant."""
    if project is None:
        return []
    from ..subtitle_rules.language_rules import project_language
    from ..subtitle_rules.subtitle_translation import translation_view
    language = project_language(project)
    imported = (project.generation_metadata.get("subtitle_imports") or {})
    track_info = imported.get("tracks", {})
    cue_info = imported.get("cues", {})
    cues = {cue.id: cue for cue in project.cues}
    external_sources = {}
    for cue in project.cues:
        record = cue_info.get(cue.id, {})
        if record.get('role') == 'original' and record.get('export_id') and record.get('source_cue'):
            external_sources.setdefault((record['export_id'], record['source_cue']), []).append(cue)
    translated = translation_view(project) if mode != "original" else {}
    wanted = None if cue_ids is None else set(cue_ids)
    tracks = None if tracks is None else set(tracks)
    result = []
    for cue in project.cues:
        if wanted is not None and cue.id not in wanted:
            continue
        info = track_info.get(cue.speaker_id, {})
        # An unlabeled independent import must not inherit the source language.
        lang = str(info.get("language") or (language if not info else "") or "")
        role = info.get("role", "")
        # Independent foreign-language imports have their own UUIDs and clock;
        # classifying their text never invents a source association.
        is_translation = role == "translation" or (role == "independent" and bool(info.get("language"))
                                                   and bool(language) and lang.split("-")[0] != language.split("-")[0])
        # A plain import need not declare its source relationship. Explicitly
        # choosing that independent track as translation is sufficient; this
        # is an operation scope, never a persisted role or inferred pairing.
        if role == 'independent' and tracks is not None and cue.speaker_id in tracks and mode != 'original':
            is_translation = True
        layer = "translation" if is_translation else "original"
        ref = TextTarget(cue.id, layer, lang, cue.speaker_id)
        source_id = ""
        source_text = ""
        if is_translation:
            association = cue_info.get(cue.id, {}).get("association") or {}
            source_id = str(association.get("cue_id") or "")
            # An external export ID is not a local cue ID. Only an explicit,
            # unique local ID can supply context; timing/order are never used.
            candidates = external_sources.get((association.get('export_id'), source_id), [])
            source = candidates[0] if len(candidates) == 1 else (
                cues.get(source_id) if association.get('project_id') == project.project_id else None)
            if source is not None and source.id != cue.id:
                source_text = source.text
                source_id = source.id
            else:
                source_id = ""
        if (mode == "both" or mode == layer) and (layer == "original" or tracks is None or ref.track_id in tracks):
            if include_empty or cue.text.strip():
                result.append(TextEntry(ref, cue.text, cue.start_ms, cue.end_ms, cue.speaker_id, source_text, source_id))
        if mode == "original":
            continue
        record = translated.get(cue.id, {})
        target = str(record.get("target") or "")
        ref = TextTarget(cue.id, "translation", target, "translation-records:" + target, "translation")
        if (tracks is None or ref.track_id in tracks) and (include_empty or str(record.get("text") or "").strip()):
            result.append(TextEntry(ref, str(record.get("text") or ""), cue.start_ms, cue.end_ms,
                                    cue.speaker_id, cue.text, cue.id))
    return result


def entry_lookup(project, *, targets=(), **kwargs):
    result = {entry.key: entry for entry in text_entries(project, **kwargs)}
    targets = [target for target in targets if target is not None]
    independent = {target.track_id for target in targets if target.layer == 'translation' and target.storage == 'cue'}
    wanted = {target.key for target in targets}
    if independent:
        result.update({entry.key: entry for entry in text_entries(project, mode='both', tracks=independent)
                       if entry.key in wanted})
    return result


def target_label(target):
    from ..i18n import tr
    from ..projects.subtitle_import import language_label
    return tr("{layer} · {language}", layer=tr("译文") if target.layer == "translation" else tr("原文"),
              language=language_label(target.language))


def track_label(project, target):
    from ..i18n import tr
    if target.storage == 'translation':
        return tr('生成译文')
    return next((speaker.name for speaker in project.speakers if speaker.id == target.track_id), tr('未命名轨道'))


def scope_entries(page, scope, *, mode="original", tracks=None):
    """Combine a text layer selection with the Studio's semantic cue scope."""
    from .studio_text_tools import scope_cue_ids, SCOPE_ALL, SCOPE_TRACK
    project = page.session.project
    entries = text_entries(project, mode=mode, tracks=tracks)
    if scope == SCOPE_ALL:
        return entries
    timeline = getattr(page, "timeline", None)
    current = str(getattr(page.session, "selected_cue_id", "") or "")
    from ..timeline.studio_edit_sequence import source_cue_id_of
    current = current if any(c.id == current for c in project.cues) else source_cue_id_of(current)
    if scope == 'selected' and getattr(timeline, 'active_subtitle_layer', '') == 'translation':
        selected = set(getattr(timeline, 'translation_selected_ids', ()))
        wanted = {value if value in {c.id for c in project.cues} else source_cue_id_of(value) for value in selected}
        return [entry for entry in entries if entry.target.cue_id in wanted]
    if scope == SCOPE_TRACK and getattr(timeline, "active_subtitle_layer", "") == "translation":
        # The generated translation lane belongs to the selected language;
        # it does not inherit style IDs from the source track.
        return [e for e in entries if e.target.storage == "translation"]
    wanted = set(scope_cue_ids(page, scope))
    return [entry for entry in entries if entry.target.cue_id in wanted]


def review_project(project, entries):
    """Small immutable review input; IDs are runtime addresses, never row numbers."""
    view = copy.copy(project)
    cues = {cue.id: cue for cue in project.cues}
    view.cues = []
    for entry in entries:
        cue = copy.copy(cues[entry.target.cue_id])
        cue.id, cue.text = entry.key, entry.text
        if entry.target.layer == "translation":
            cue.original_text, cue.evidence_refs = entry.text, []
        view.cues.append(cue)
    view._review_text_entries = {entry.key: entry for entry in entries}
    view.studio_state = dict(project.studio_state or {})
    view.generation_metadata = dict(project.generation_metadata or {})
    for key in ('translation_records', 'translations', 'translation_glossary', 'subtitle_imports'):
        if key in view.generation_metadata:
            view.generation_metadata[key] = copy.deepcopy(view.generation_metadata[key])
    return view


def bind_occurrence(hit, entry):
    return replace(hit, cue_id=entry.target.cue_id, target=entry.target, baseline=entry.text, context_snapshot=entry)


def navigate_target(page, target):
    """Select the real stored cue, then explicitly select its text layer."""
    entry = entry_lookup(page.session.project, targets=[target]).get(target.key)
    if entry is None or entry.target != target:
        return False
    if target.storage == 'translation':
        from ..subtitle_rules.subtitle_translation import container_target
        if target.language != container_target(page.session.project):
            return False
    page.select_cue(target.cue_id)
    timeline = getattr(page, "timeline", None)
    if timeline is None:
        return
    if target.storage == "translation":
        from ..subtitle_rules.subtitle_translation import container_target
        if target.language != container_target(page.session.project):
            return
        if not timeline.bilingual:
            timeline.set_bilingual(True)
        timeline.select_translation(target.cue_id)
    else:
        timeline.set_subtitle_layer("original")
    from .studio_translation_edit import sync_editor_layer
    sync_editor_layer(page)
    return True
